import { Badge, type Tone } from "@/components/ui/Badge";
import type { RunStatus, StepStatus } from "@/lib/types";

const TONES: Record<RunStatus | StepStatus, Tone> = {
  queued: "neutral",
  running: "info",
  waiting: "warning",
  succeeded: "success",
  failed: "danger",
  cancelled: "neutral",
  skipped: "neutral",
};

export function RunStatusBadge({ status }: { status: RunStatus | StepStatus }) {
  return <Badge tone={TONES[status]}>{status}</Badge>;
}
