from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.api.deps import CurrentUser, QueueDep, SessionDep
from app.config import get_settings
from app.core.errors import AuthenticationError
from app.core.permissions import Role
from app.core.rate_limit import client_ip, limit_by_ip
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
    WorkspaceSummary,
)
from app.services import auth as auth_service
from app.services import workspaces as workspace_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "ff_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"

auth_rate_limit = Depends(limit_by_ip("auth", limit=20, window_seconds=60))
# Every page load refreshes the session, so refresh gets its own, more generous budget.
refresh_rate_limit = Depends(limit_by_ip("auth_refresh", limit=120, window_seconds=60))


def _client(request: Request) -> auth_service.ClientInfo:
    return auth_service.ClientInfo(
        user_agent=request.headers.get("user-agent"), ip_address=client_ip(request)
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _token_response(tokens: auth_service.SessionTokens, response: Response) -> TokenResponse:
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=get_settings().access_token_ttl_minutes * 60,
        user=UserOut.model_validate(tokens.user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[auth_rate_limit],
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    queue: QueueDep,
) -> TokenResponse:
    user = await auth_service.register(
        session, queue, email=body.email, password=body.password, full_name=body.full_name
    )
    tokens = await auth_service.start_session(session, user, _client(request))
    return _token_response(tokens, response)


@router.post("/login", response_model=TokenResponse, dependencies=[auth_rate_limit])
async def login(
    body: LoginRequest, request: Request, response: Response, session: SessionDep
) -> TokenResponse:
    user = await auth_service.authenticate(session, email=body.email, password=body.password)
    tokens = await auth_service.start_session(session, user, _client(request))
    return _token_response(tokens, response)


@router.post("/refresh", response_model=TokenResponse, dependencies=[refresh_rate_limit])
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    ff_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not ff_refresh:
        raise AuthenticationError("No refresh token")
    tokens = await auth_service.rotate_refresh_token(session, ff_refresh, _client(request))
    return _token_response(tokens, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDep,
    ff_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    if ff_refresh:
        await auth_service.logout(session, ff_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(user: CurrentUser, response: Response, session: SessionDep) -> None:
    await auth_service.logout_everywhere(session, user.id)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(body: TokenRequest, session: SessionDep) -> None:
    await auth_service.verify_email(session, body.token)


@router.post(
    "/resend-verification",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[auth_rate_limit],
)
async def resend_verification(user: CurrentUser, session: SessionDep, queue: QueueDep) -> None:
    await auth_service.resend_verification(session, queue, user)


@router.post(
    "/forgot-password", status_code=status.HTTP_202_ACCEPTED, dependencies=[auth_rate_limit]
)
async def forgot_password(
    body: ForgotPasswordRequest, session: SessionDep, queue: QueueDep
) -> dict[str, str]:
    await auth_service.request_password_reset(session, queue, body.email)
    return {"status": "If an account exists for this email, a reset link has been sent."}


@router.post(
    "/reset-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[auth_rate_limit]
)
async def reset_password(body: ResetPasswordRequest, session: SessionDep) -> None:
    await auth_service.reset_password(session, body.token, body.password)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, session: SessionDep) -> MeResponse:
    memberships = await workspace_service.list_for_user(session, user.id)
    return MeResponse(
        user=UserOut.model_validate(user),
        workspaces=[
            WorkspaceSummary(
                id=m.workspace.id,
                name=m.workspace.name,
                slug=m.workspace.slug,
                plan=m.workspace.plan,
                role=Role(m.role),
            )
            for m in memberships
        ],
    )


@router.patch("/me", response_model=UserOut)
async def update_me(body: UpdateProfileRequest, user: CurrentUser, session: SessionDep) -> UserOut:
    updated = await auth_service.update_profile(session, user, full_name=body.full_name)
    return UserOut.model_validate(updated)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, session: SessionDep, response: Response
) -> None:
    await auth_service.change_password(session, user, body.current_password, body.new_password)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
