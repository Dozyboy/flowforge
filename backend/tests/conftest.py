"""Shared fixtures.

Tests run against real PostgreSQL and Redis from docker-compose, using a separate database
(`flowforge_test`) and Redis DB 15. The LLM is `FakeLLMClient`, jobs are captured by
`InMemoryJobQueue`, and outbound HTTP is mocked with respx.
"""

import os
import tempfile

from cryptography.fernet import Fernet

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge_test",
        ),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
        "LLM_PROVIDER": "fake",
        "RATE_LIMIT_ENABLED": "false",
        "JWT_SECRET": "test-secret-that-is-long-enough-for-hs256",
        "CREDENTIALS_KEY": Fernet.generate_key().decode(),
        "UPLOAD_DIR": tempfile.mkdtemp(prefix="flowforge-test-"),
    }
)

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import FakeLLMClient, get_llm_client
from app.core.permissions import Role
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_engine, get_session_factory
from app.engine.executor import EngineDeps, RunExecutor
from app.main import app as fastapi_app
from app.models import Membership, User, Workspace
from app.services import workspaces as workspace_service
from app.services.jobs import InMemoryJobQueue, get_job_queue

TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with get_engine().begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await get_redis().flushdb()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as db_session:
        yield db_session


@pytest.fixture
def llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def executor(llm: FakeLLMClient, queue: InMemoryJobQueue, http: httpx.AsyncClient) -> RunExecutor:
    return RunExecutor(
        EngineDeps(session_factory=get_session_factory(), llm=llm, http=http, queue=queue)
    )


@pytest.fixture
async def client(llm: FakeLLMClient, queue: InMemoryJobQueue) -> AsyncIterator[AsyncClient]:
    fastapi_app.dependency_overrides[get_llm_client] = lambda: llm
    fastapi_app.dependency_overrides[get_job_queue] = lambda: queue
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    fastapi_app.dependency_overrides.clear()


@dataclass
class Account:
    user: User
    workspace: Workspace
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def ws(self) -> str:
        return f"/api/v1/workspaces/{self.workspace.id}"


class AccountFactory:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user(self, email: str | None = None, name: str = "Test User") -> User:
        user = User(
            email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password(TEST_PASSWORD),
            full_name=name,
        )
        self.session.add(user)
        await self.session.commit()
        return user

    async def owner(self, workspace_name: str = "Acme Ops") -> Account:
        user = await self.user()
        workspace = await workspace_service.create_workspace(self.session, user, workspace_name)
        return Account(user=user, workspace=workspace, token=create_access_token(user.id))

    async def member(self, account: Account, role: Role) -> Account:
        user = await self.user()
        self.session.add(Membership(workspace_id=account.workspace.id, user_id=user.id, role=role))
        await self.session.commit()
        return Account(user=user, workspace=account.workspace, token=create_access_token(user.id))


@pytest.fixture
def accounts(session: AsyncSession) -> AccountFactory:
    return AccountFactory(session)
