"use client";

import Link from "next/link";
import { X } from "lucide-react";

import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { useWorkspace } from "@/features/workspace/workspace-context";
import type { RunDetail, Step } from "@/lib/types";

export function RunPanel({
  run,
  onSelectNode,
  onClose,
}: {
  run: RunDetail;
  onSelectNode: (nodeId: string) => void;
  onClose: () => void;
}) {
  const { basePath } = useWorkspace();
  const startedAt = (step: Step) =>
    step.started_at ? Date.parse(step.started_at) : Number.POSITIVE_INFINITY;
  const steps = [...run.steps].sort((a, b) => startedAt(a) - startedAt(b));
  return (
    <div className="absolute inset-x-4 bottom-4 z-10 max-h-64 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
      <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-2">
        <span className="text-sm font-medium text-slate-900">Test run</span>
        <RunStatusBadge status={run.status} />
        {run.error && <span className="truncate text-xs text-rose-600">{run.error}</span>}
        <Link
          href={`${basePath}/runs/${run.id}`}
          className="ml-auto text-xs font-medium text-indigo-600 hover:underline"
        >
          Open run details
        </Link>
        <button type="button" aria-label="Close run panel" onClick={onClose}>
          <X className="size-4 text-slate-400" />
        </button>
      </div>
      <ul className="max-h-48 divide-y divide-slate-50 overflow-y-auto text-sm">
        {steps.map((step) => (
          <li key={step.id}>
            <button
              type="button"
              onClick={() => onSelectNode(step.node_id)}
              className="flex w-full items-center gap-3 px-4 py-1.5 text-left hover:bg-slate-50"
            >
              <RunStatusBadge status={step.status} />
              <span className="font-mono text-xs text-slate-700">{step.node_id}</span>
              {step.branch && <span className="text-xs text-slate-500">→ {step.branch}</span>}
              {step.error && <span className="truncate text-xs text-rose-600">{step.error}</span>}
              <span className="ml-auto text-xs text-slate-400">
                {step.duration_ms !== null ? `${step.duration_ms} ms` : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
