import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import Usage
from app.models import LlmUsage


def record_llm_usage(
    session: AsyncSession, workspace_id: uuid.UUID | None, kind: str, usage: Usage
) -> None:
    session.add(
        LlmUsage(
            workspace_id=workspace_id,
            kind=kind,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
        )
    )


@dataclass(frozen=True)
class UsageByKind:
    kind: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


async def summarize(
    session: AsyncSession, workspace_id: uuid.UUID, since: datetime
) -> list[UsageByKind]:
    rows = await session.execute(
        select(
            LlmUsage.kind,
            func.count(),
            func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            func.coalesce(func.sum(LlmUsage.cost_usd), 0),
        )
        .where(LlmUsage.workspace_id == workspace_id, LlmUsage.created_at >= since)
        .group_by(LlmUsage.kind)
        .order_by(LlmUsage.kind)
    )
    return [
        UsageByKind(kind, int(calls), int(prompt), int(completion), Decimal(cost))
        for kind, calls, prompt, completion, cost in rows.all()
    ]
