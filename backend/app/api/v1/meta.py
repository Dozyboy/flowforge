"""Catalogues the editor needs: node types, credential types, templates, plans."""

from fastapi import APIRouter

from app.engine.credential_types import CREDENTIAL_TYPES
from app.engine.nodes.registry import registry
from app.schemas.credential import CredentialTypeOut
from app.schemas.workflow import NodeTypeOut, TemplateOut
from app.schemas.workspace import PlanOut
from app.services import plans
from app.services import workflows as workflow_service

router = APIRouter(tags=["catalog"])


@router.get("/node-types", response_model=list[NodeTypeOut])
async def node_types() -> list[NodeTypeOut]:
    return [NodeTypeOut(**node_type.describe()) for node_type in registry.all()]


@router.get("/credential-types", response_model=list[CredentialTypeOut])
async def credential_types() -> list[CredentialTypeOut]:
    return [CredentialTypeOut(**t.describe()) for t in CREDENTIAL_TYPES.values()]


@router.get("/templates", response_model=list[TemplateOut])
async def templates() -> list[TemplateOut]:
    return [TemplateOut(**t) for t in workflow_service.list_templates()]


@router.get("/plans", response_model=list[PlanOut])
async def list_plans() -> list[PlanOut]:
    return [PlanOut.model_validate(plan) for plan in plans.PLANS.values()]
