import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel


class CredentialFieldOut(ApiModel):
    name: str
    label: str
    secret: bool
    multiline: bool


class CredentialTypeOut(ApiModel):
    type: str
    label: str
    description: str
    fields: list[CredentialFieldOut]


class CredentialCreate(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=40)
    data: dict[str, str]


class CredentialUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    data: dict[str, str] | None = None


class CredentialOut(ApiModel):
    """Metadata only: secret values are never returned."""

    id: uuid.UUID
    name: str
    type: str
    created_at: datetime
    updated_at: datetime
