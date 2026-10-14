import uuid

from app.core.crypto import decrypt_json, encrypt_json
from app.core.permissions import Role
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_hashing() -> None:
    hashed = hash_password("s3cret-password")
    assert hashed != "s3cret-password"
    assert verify_password("s3cret-password", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id)) == user_id


def test_tampered_access_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    assert decode_access_token(token[:-2] + "xx") is None


def test_api_key_format() -> None:
    key, prefix = generate_api_key()
    assert key.startswith("ff_")
    assert key.startswith(prefix)
    assert len(hash_token(key)) == 64


def test_credentials_are_encrypted_at_rest() -> None:
    secret = {"token": "xoxb-very-secret"}
    encrypted = encrypt_json(secret)
    assert "xoxb" not in encrypted
    assert decrypt_json(encrypted) == secret


def test_role_hierarchy() -> None:
    assert Role.OWNER.at_least(Role.ADMIN)
    assert Role.ADMIN.at_least(Role.MEMBER)
    assert not Role.VIEWER.at_least(Role.MEMBER)
    assert Role.MEMBER.at_least(Role.MEMBER)
