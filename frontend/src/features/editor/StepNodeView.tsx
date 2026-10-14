"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AlertTriangle } from "lucide-react";
import { memo } from "react";

import { useEditor } from "@/features/editor/editor-context";
import { outputHandles, type StepNode } from "@/features/editor/graph";
import { CATEGORY_STYLE, NodeIcon } from "@/features/editor/NodeIcon";
import { cn } from "@/lib/cn";
import type { StepStatus } from "@/lib/types";

const STATUS_RING: Record<StepStatus, string> = {
  running: "ring-4 ring-indigo-300 animate-pulse",
  succeeded: "ring-4 ring-emerald-300",
  failed: "ring-4 ring-rose-300",
  skipped: "opacity-50",
  waiting: "ring-4 ring-amber-300",
};

function StepNodeViewInner({ id, data, selected }: NodeProps<StepNode>) {
  const { types, issuesByNode, liveStatus } = useEditor();
  const info = types.get(data.nodeType);
  const handles = outputHandles(info, data.config);
  const issues = issuesByNode.get(id);
  const status = liveStatus.get(id);
  const isTrigger = data.nodeType.startsWith("trigger_");
  const category = CATEGORY_STYLE[info?.category ?? "data"];

  return (
    <div
      className={cn(
        "w-60 rounded-lg border bg-white shadow-sm",
        selected ? "border-indigo-500" : "border-slate-200",
        status && STATUS_RING[status],
      )}
      data-testid={`node-${id}`}
      data-status={status ?? ""}
    >
      {!isTrigger && <Handle type="target" position={Position.Top} className="!bg-slate-400" />}
      <div className="flex items-center gap-2 px-3 py-2.5">
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-md",
            category.color,
          )}
        >
          <NodeIcon name={info?.icon ?? "box"} className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900">{data.label}</p>
          <p className="truncate text-xs text-slate-500">
            {info?.label ?? data.nodeType} · <span className="font-mono">{id}</span>
          </p>
        </div>
        {issues && issues.length > 0 && (
          <span title={issues.join("\n")} className="text-amber-500">
            <AlertTriangle className="size-4" aria-label={`${issues.length} problem(s)`} />
          </span>
        )}
      </div>
      {handles.length === 0 ? (
        <Handle type="source" position={Position.Bottom} className="!bg-slate-400" />
      ) : (
        <div className="flex justify-around gap-1 border-t border-slate-100 px-2 pt-1 pb-2">
          {handles.map((handle) => (
            <div key={handle} className="relative flex flex-col items-center">
              <span className="max-w-20 truncate text-[10px] text-slate-500">{handle}</span>
              <Handle
                type="source"
                id={handle}
                position={Position.Bottom}
                className="!relative !left-0 !mt-1 !translate-x-0 !bg-indigo-500"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const StepNodeView = memo(StepNodeViewInner);
