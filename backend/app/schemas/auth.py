import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.core.permissions import Role
from app.schemas.common import ApiModel

Password = Field(min_length=8, max_length=128)


class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Password
    full_name: str = Field(min_length=1, max_length=200)


class LoginRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenRequest(ApiModel):
    token: str = Field(min_length=10, max_length=200)


class ForgotPasswordRequest(ApiModel):
    email: EmailStr


class ResetPasswordRequest(ApiModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Password


class ChangePasswordRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Password


class UpdateProfileRequest(ApiModel):
    full_name: str = Field(min_length=1, max_length=200)


class UserOut(ApiModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_email_verified: bool
    created_at: datetime


class WorkspaceSummary(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    role: Role


class MeResponse(ApiModel):
    user: UserOut
    workspaces: list[WorkspaceSummary]


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut
