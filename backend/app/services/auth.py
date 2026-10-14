import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    generate_token,
    hash_password,
    hash_password_async,
    hash_token,
    verify_password_async,
)
from app.models import RefreshToken, User, UserToken, UserTokenPurpose
from app.services import email as email_service
from app.services.jobs import JobQueue

logger = structlog.get_logger(__name__)

# Used to keep login timing similar whether or not the email exists.
_DUMMY_PASSWORD_HASH = hash_password("timing-equalizer")


@dataclass(frozen=True)
class SessionTokens:
    user: User
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalize_email(email)))


async def register(
    session: AsyncSession, queue: JobQueue, *, email: str, password: str, full_name: str
) -> User:
    if await get_user_by_email(session, email):
        raise ConflictError("An account with this email already exists")
    user = User(
        email=normalize_email(email),
        password_hash=await hash_password_async(password),
        full_name=full_name.strip(),
    )
    session.add(user)
    await session.flush()
    token = await create_user_token(session, user, UserTokenPurpose.VERIFY_EMAIL)
    await session.commit()
    await email_service.queue_email(queue, email_service.verification_email(user.email, token))
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if user is None:
        await verify_password_async(password, _DUMMY_PASSWORD_HASH)
        raise AuthenticationError("Invalid email or password")
    if not await verify_password_async(password, user.password_hash) or not user.is_active:
        raise AuthenticationError("Invalid email or password")
    return user


async def start_session(session: AsyncSession, user: User, client: ClientInfo) -> SessionTokens:
    raw, _ = await _issue_refresh_token(session, user.id, uuid.uuid4(), client)
    await session.commit()
    return SessionTokens(user, create_access_token(user.id), raw)


async def _issue_refresh_token(
    session: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID, client: ClientInfo
) -> tuple[str, RefreshToken]:
    raw = generate_token(32)
    token = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        family_id=family_id,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_ttl_days),
        user_agent=(client.user_agent or "")[:500] or None,
        ip_address=client.ip_address,
    )
    session.add(token)
    await session.flush()
    return raw, token


async def rotate_refresh_token(
    session: AsyncSession, raw_token: str, client: ClientInfo
) -> SessionTokens:
    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    now = datetime.now(UTC)
    if stored is None:
        raise AuthenticationError("Invalid refresh token")

    if stored.revoked_at is not None:
        if stored.replaced_by_id is not None:
            # A rotated token was presented again: it was most likely stolen. Revoke the family.
            await _revoke_family(session, stored.family_id)
            await session.commit()
            logger.warning("refresh_token_reuse_detected", user_id=str(stored.user_id))
        raise AuthenticationError("Refresh token has been revoked")

    if stored.expires_at <= now:
        raise AuthenticationError("Refresh token has expired")

    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not active")

    new_raw, new_stored = await _issue_refresh_token(session, user.id, stored.family_id, client)
    stored.revoked_at = now
    stored.replaced_by_id = new_stored.id
    await session.commit()
    return SessionTokens(user, create_access_token(user.id), new_raw)


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def logout(session: AsyncSession, raw_token: str) -> None:
    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    )
    if stored is not None:
        await _revoke_family(session, stored.family_id)
        await session.commit()


async def logout_everywhere(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()


async def create_user_token(session: AsyncSession, user: User, purpose: UserTokenPurpose) -> str:
    raw = generate_token(32)
    session.add(
        UserToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=get_settings().email_token_ttl_hours),
        )
    )
    await session.flush()
    return raw


async def _consume_user_token(
    session: AsyncSession, raw_token: str, purpose: UserTokenPurpose
) -> User:
    token = await session.scalar(
        select(UserToken).where(
            UserToken.token_hash == hash_token(raw_token), UserToken.purpose == purpose
        )
    )
    now = datetime.now(UTC)
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise AppError("This link is invalid or has expired")
    user = await session.get(User, token.user_id)
    if user is None:
        raise AppError("This link is invalid or has expired")
    token.used_at = now
    return user


async def verify_email(session: AsyncSession, raw_token: str) -> User:
    user = await _consume_user_token(session, raw_token, UserTokenPurpose.VERIFY_EMAIL)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await session.commit()
    return user


async def resend_verification(session: AsyncSession, queue: JobQueue, user: User) -> None:
    if user.is_email_verified:
        return
    token = await create_user_token(session, user, UserTokenPurpose.VERIFY_EMAIL)
    await session.commit()
    await email_service.queue_email(queue, email_service.verification_email(user.email, token))


async def request_password_reset(session: AsyncSession, queue: JobQueue, email: str) -> None:
    """Always succeeds for the caller, so it cannot be used to discover which emails exist."""
    user = await get_user_by_email(session, email)
    if user is None or not user.is_active:
        return
    token = await create_user_token(session, user, UserTokenPurpose.RESET_PASSWORD)
    await session.commit()
    await email_service.queue_email(queue, email_service.password_reset_email(user.email, token))


async def reset_password(session: AsyncSession, raw_token: str, new_password: str) -> None:
    user = await _consume_user_token(session, raw_token, UserTokenPurpose.RESET_PASSWORD)
    user.password_hash = await hash_password_async(new_password)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await session.flush()
    await logout_everywhere(session, user.id)


async def change_password(
    session: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    if not await verify_password_async(current_password, user.password_hash):
        raise AuthenticationError("Current password is incorrect")
    user.password_hash = await hash_password_async(new_password)
    await session.flush()
    await logout_everywhere(session, user.id)


async def update_profile(session: AsyncSession, user: User, *, full_name: str) -> User:
    user.full_name = full_name.strip()
    await session.commit()
    return user
