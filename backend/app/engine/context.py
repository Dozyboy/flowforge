from typing import Any

from app.models import Run, StepRun, StepStatus


def build_context(run: Run, workflow_name: str, steps: dict[str, StepRun]) -> dict[str, Any]:
    """The variables available to {{ expressions }} while a run executes."""
    return {
        "trigger": run.trigger_payload or {},
        "steps": {
            node_id: {"output": step.output, "status": step.status, "branch": step.branch}
            for node_id, step in steps.items()
            if step.status in (StepStatus.SUCCEEDED, StepStatus.FAILED)
        },
        "run": {"id": str(run.id), "trigger_type": run.trigger_type},
        "workflow": {"id": str(run.workflow_id), "name": workflow_name},
    }
