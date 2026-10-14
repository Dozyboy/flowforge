from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserTokenPurpose
from app.services import auth as auth_service
from app.services.jobs import InMemoryJobQueue
from tests.conftest import TEST_PASSWORD, AccountFactory

REGISTER = {"email": "Ana@Example.com", "password": "a-strong-password", "full_name": "Ana"}


async def test_register_logs_in_and_sends_verification_email(
    client: AsyncClient, queue: InMemoryJobQueue
) -> None:
    response = await client.post("/api/v1/auth/register", json=REGISTER)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ana@example.com"
    assert body["user"]["is_email_verified"] is False
    assert body["access_token"]
    assert "ff_refresh" in response.cookies
    emails = queue.named("send_email")
    assert emails[0]["to"] == "ana@example.com"
    assert "/verify-email?token=" in emails[0]["text"]


async def test_duplicate_email_is_rejected(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER)
    response = await client.post(
        "/api/v1/auth/register", json={**REGISTER, "email": "ANA@example.com"}
    )
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "conflict"


async def test_validation_errors_use_problem_details(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={"email": "nope", "password": "short", "full_name": ""}
    )
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert {"email", "password", "full_name"} <= fields


async def test_login_with_wrong_password(client: AsyncClient, accounts: AccountFactory) -> None:
    user = await accounts.user()
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"

    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "whatever-123"}
    )
    assert unknown.json()["detail"] == "Invalid email or password"


async def test_refresh_rotates_token_and_detects_reuse(
    client: AsyncClient, accounts: AccountFactory
) -> None:
    user = await accounts.user()
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    first_refresh = login.cookies["ff_refresh"]

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    second_refresh = rotated.cookies["ff_refresh"]
    assert second_refresh != first_refresh

    # Replaying the first token revokes the whole family, including the newest token.
    client.cookies.set("ff_refresh", first_refresh, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    client.cookies.set("ff_refresh", second_refresh, path="/api/v1/auth")
    after_reuse = await client.post("/api/v1/auth/refresh")
    assert after_reuse.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient, accounts: AccountFactory) -> None:
    user = await accounts.user()
    await client.post("/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_me_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


async def test_me_lists_workspaces(client: AsyncClient, accounts: AccountFactory) -> None:
    account = await accounts.owner("Acme")
    response = await client.get("/api/v1/auth/me", headers=account.headers)
    assert response.status_code == 200
    assert response.json()["workspaces"] == [
        {
            "id": str(account.workspace.id),
            "name": "Acme",
            "slug": "acme",
            "plan": "free",
            "role": "owner",
        }
    ]


async def test_email_verification_token_is_single_use(
    client: AsyncClient, session: AsyncSession, accounts: AccountFactory
) -> None:
    user = await accounts.user()
    token = await auth_service.create_user_token(session, user, UserTokenPurpose.VERIFY_EMAIL)
    await session.commit()

    first = await client.post("/api/v1/auth/verify-email", json={"token": token})
    second = await client.post("/api/v1/auth/verify-email", json={"token": token})

    assert first.status_code == 204
    assert second.status_code == 400
    await session.refresh(user)
    assert user.email_verified_at is not None


async def test_password_reset_flow(
    client: AsyncClient, queue: InMemoryJobQueue, accounts: AccountFactory, session: AsyncSession
) -> None:
    user = await accounts.user()
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    old_refresh = login.cookies["ff_refresh"]

    response = await client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert response.status_code == 202
    link = queue.named("send_email")[0]["text"]
    token = link.split("token=")[1].strip()

    reset = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "brand-new-password"}
    )
    assert reset.status_code == 204

    client.cookies.set("ff_refresh", old_refresh, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "brand-new-password"}
    )
    assert new_login.status_code == 200


async def test_forgot_password_does_not_reveal_unknown_emails(
    client: AsyncClient, queue: InMemoryJobQueue
) -> None:
    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert response.status_code == 202
    assert queue.named("send_email") == []


async def test_change_password_requires_current_password(
    client: AsyncClient, accounts: AccountFactory, session: AsyncSession
) -> None:
    account = await accounts.owner()
    wrong = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "nope", "new_password": "another-password"},
        headers=account.headers,
    )
    assert wrong.status_code == 401

    ok = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": TEST_PASSWORD, "new_password": "another-password"},
        headers=account.headers,
    )
    assert ok.status_code == 204
    user = await session.scalar(select(User).where(User.id == account.user.id))
    assert user is not None
