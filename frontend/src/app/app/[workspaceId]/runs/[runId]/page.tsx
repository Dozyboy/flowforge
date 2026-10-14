"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Background, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { RotateCcw, Square } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState, PageLoader } from "@/components/ui/Feedback";
import { useToast } from "@/components/ui/Toaster";
import { EditorContext } from "@/features/editor/editor-context";
import { toFlow } from "@/features/editor/graph";
import { StepNodeView } from "@/features/editor/StepNodeView";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { NodeTypeInfo, RunDetail, RunSummary, Step, StepStatus } from "@/lib/types";

const NODE_TYPES = { step: StepNodeView };
const TERMINAL = ["succeeded", "failed", "cancelled"];

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
      {JSON.stringify(value ?? null, null, 2)}
    </pre>
  );
}

function StepDetails({ step }: { step: Step }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <RunStatusBadge status={step.status} />
        <span className="font-mono text-slate-700">{step.node_id}</span>
        <span className="text-slate-500">{step.node_type}</span>
        {step.branch && <span className="text-slate-500">took branch “{step.branch}”</span>}
        {step.attempt > 1 && <span className="text-amber-600">{step.attempt} attempts</span>}
        {step.duration_ms !== null && <span className="text-slate-400">{step.duration_ms} ms</span>}
      </div>
      {step.error && (
        <p className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{step.error}</p>
      )}
      {step.resume_at && (
        <p className="text-sm text-amber-700">Resumes at {formatDateTime(step.resume_at)}</p>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-semibold text-slate-500 uppercase">
            Input (rendered config)
          </p>
          <Json value={step.input} />
        </div>
        <div>
          <p className="mb-1 text-xs font-semibold text-slate-500 uppercase">Output</p>
          <Json value={step.output} />
        </div>
      </div>
    </div>
  );
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { workspace, basePath, can } = useWorkspace();
  const router = useRouter();
  const toast = useToast();
  const [selected, setSelected] = useState<string | null>(null);

  const run = useQuery({
    queryKey: queryKeys.run(workspace.id, runId),
    queryFn: () => api<RunDetail>(`/workspaces/${workspace.id}/runs/${runId}`),
    refetchInterval: (query) =>
      query.state.data && TERMINAL.includes(query.state.data.status) ? false : 5000,
  });
  const nodeTypes = useQuery({
    queryKey: queryKeys.nodeTypes,
    queryFn: () => api<NodeTypeInfo[]>("/node-types"),
    staleTime: Infinity,
  });
  const cancel = useMutation({
    mutationFn: () => api(`/workspaces/${workspace.id}/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => void run.refetch(),
    onError: (err) => toast.error(errorMessage(err)),
  });
  const retry = useMutation({
    mutationFn: (fromFailedStep: boolean) =>
      api<RunSummary>(`/workspaces/${workspace.id}/runs/${runId}/retry`, {
        method: "POST",
        body: { from_failed_step: fromFailedStep },
      }),
    onSuccess: (next) => router.push(`${basePath}/runs/${next.id}`),
    onError: (err) => toast.error(errorMessage(err)),
  });

  const flow = useMemo(() => (run.data ? toFlow(run.data.graph) : null), [run.data]);
  const liveStatus = useMemo(
    () => new Map<string, StepStatus>(run.data?.steps.map((s) => [s.node_id, s.status]) ?? []),
    [run.data],
  );
  const types = useMemo(() => new Map(nodeTypes.data?.map((t) => [t.type, t])), [nodeTypes.data]);

  if (run.isPending || nodeTypes.isPending) return <PageLoader />;
  if (run.isError) {
    return (
      <div className="p-4 sm:p-8">
        <ErrorState message={errorMessage(run.error)} />
      </div>
    );
  }
  const data = run.data;
  // Executed steps in start order; skipped steps (never started) go last.
  const startedAt = (step: Step) =>
    step.started_at ? Date.parse(step.started_at) : Number.POSITIVE_INFINITY;
  const steps = [...data.steps].sort((a, b) => startedAt(a) - startedAt(b));
  const focused =
    steps.find((s) => s.node_id === selected) ?? steps.find((s) => s.status === "failed");

  return (
    <>
      <PageHeader
        title={data.workflow_name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <RunStatusBadge status={data.status} />
            <span>
              {data.trigger_type} run · {formatDateTime(data.created_at)}
            </span>
            {data.retry_of_id && (
              <Link
                href={`${basePath}/runs/${data.retry_of_id}`}
                className="text-indigo-600 hover:underline"
              >
                retry of an earlier run
              </Link>
            )}
          </span>
        }
        actions={
          can("member") && (
            <>
              {!TERMINAL.includes(data.status) && (
                <Button
                  variant="secondary"
                  onClick={() => cancel.mutate()}
                  loading={cancel.isPending}
                >
                  <Square className="size-4" aria-hidden /> Cancel
                </Button>
              )}
              {(data.status === "failed" || data.status === "cancelled") && (
                <>
                  <Button
                    variant="secondary"
                    onClick={() => retry.mutate(false)}
                    loading={retry.isPending}
                  >
                    Retry from start
                  </Button>
                  <Button onClick={() => retry.mutate(true)} loading={retry.isPending}>
                    <RotateCcw className="size-4" aria-hidden /> Retry from failed step
                  </Button>
                </>
              )}
            </>
          )
        }
      />
      <div className="space-y-6 p-4 sm:p-8">
        {data.error && <ErrorState message={data.error} />}
        {flow && (
          <Card className="h-80 overflow-hidden">
            <EditorContext.Provider
              value={{
                types,
                credentials: [],
                workflows: [],
                currentWorkflowId: data.workflow_id,
                issuesByNode: new Map(),
                liveStatus,
                readOnly: true,
              }}
            >
              <ReactFlowProvider>
                <ReactFlow
                  nodes={flow.nodes}
                  edges={flow.edges}
                  nodeTypes={NODE_TYPES}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  onNodeClick={(_, node) => setSelected(node.id)}
                  fitView
                  fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                  proOptions={{ hideAttribution: true }}
                >
                  <Background gap={16} />
                </ReactFlow>
              </ReactFlowProvider>
            </EditorContext.Provider>
          </Card>
        )}
        <div className="grid gap-6 xl:grid-cols-3">
          <Card>
            <CardHeader title="Timeline" />
            <ol className="divide-y divide-slate-100">
              {steps.map((step) => (
                <li key={step.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(step.node_id)}
                    className={cn(
                      "flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm hover:bg-slate-50",
                      focused?.id === step.id && "bg-indigo-50/60",
                    )}
                  >
                    <RunStatusBadge status={step.status} />
                    <span className="flex-1 truncate font-mono text-xs text-slate-700">
                      {step.node_id}
                    </span>
                    <span className="text-xs text-slate-400">
                      {step.duration_ms !== null ? `${step.duration_ms} ms` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </Card>
          <Card className="xl:col-span-2">
            <CardHeader title={focused ? `Step: ${focused.node_id}` : "Trigger payload"} />
            <CardBody>
              {focused ? <StepDetails step={focused} /> : <Json value={data.trigger_payload} />}
            </CardBody>
          </Card>
        </div>
        {data.children.length > 0 && (
          <Card>
            <CardHeader title={`Child runs (${data.children.length})`} />
            <ul className="divide-y divide-slate-100">
              {data.children.map((child) => (
                <li key={child.id} className="flex items-center gap-3 px-5 py-2 text-sm">
                  <RunStatusBadge status={child.status} />
                  <Link
                    href={`${basePath}/runs/${child.id}`}
                    className="font-mono text-xs text-indigo-600 hover:underline"
                  >
                    {child.id.slice(0, 8)}
                  </Link>
                  <code className="truncate text-xs text-slate-500">
                    {JSON.stringify(child.trigger_payload)}
                  </code>
                  {child.error && (
                    <span className="truncate text-xs text-rose-600">{child.error}</span>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
