"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, Spinner } from "@/components/ui/Feedback";
import { Select } from "@/components/ui/Field";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { duration, timeAgo } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Page, RunSummary, WorkflowSummary } from "@/lib/types";

const PAGE_SIZE = 25;
const STATUSES = ["queued", "running", "waiting", "succeeded", "failed", "cancelled"];

function seconds(run: RunSummary): number | null {
  if (!run.started_at || !run.finished_at) return null;
  return (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000;
}

function RunsContent() {
  const { workspace, basePath } = useWorkspace();
  const params = useSearchParams();
  const router = useRouter();
  const status = params.get("status") ?? undefined;
  const workflowId = params.get("workflow") ?? undefined;
  const offset = Number(params.get("offset") ?? 0);

  const setParam = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    router.replace(`${basePath}/runs?${next.toString()}`);
  };

  const filters = { status, workflow_id: workflowId, offset };
  const runs = useQuery({
    queryKey: queryKeys.runList(workspace.id, filters),
    queryFn: () =>
      api<Page<RunSummary>>(`/workspaces/${workspace.id}/runs`, {
        query: { ...filters, limit: PAGE_SIZE },
      }),
    placeholderData: keepPreviousData,
  });
  const workflows = useQuery({
    queryKey: queryKeys.workflows(workspace.id),
    queryFn: () => api<WorkflowSummary[]>(`/workspaces/${workspace.id}/workflows`),
  });

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every execution, with each step's input, output and errors."
      />
      <div className="space-y-4 p-4 sm:p-8">
        <div className="flex flex-wrap gap-2">
          <Select
            aria-label="Filter by workflow"
            className="w-64"
            value={workflowId ?? ""}
            onChange={(e) => setParam("workflow", e.target.value || undefined)}
          >
            <option value="">All workflows</option>
            {workflows.data?.map((wf) => (
              <option key={wf.id} value={wf.id}>
                {wf.name}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Filter by status"
            className="w-44"
            value={status ?? ""}
            onChange={(e) => setParam("status", e.target.value || undefined)}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </div>
        {runs.isError && <ErrorState message={errorMessage(runs.error)} />}
        <Card className="overflow-hidden">
          {runs.isPending ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : runs.data?.items.length === 0 ? (
            <EmptyState icon={<History className="size-5" />} title="No runs match these filters" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm">
                <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                  <tr>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Workflow</th>
                    <th className="px-4 py-3">Trigger</th>
                    <th className="px-4 py-3">Started</th>
                    <th className="px-4 py-3">Duration</th>
                    <th className="px-4 py-3">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {runs.data?.items.map((run) => (
                    <tr key={run.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <Link href={`${basePath}/runs/${run.id}`} aria-label={`Open run ${run.id}`}>
                          <RunStatusBadge status={run.status} />
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          href={`${basePath}/runs/${run.id}`}
                          className="font-medium text-slate-900 hover:text-indigo-700"
                        >
                          {run.workflow_name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{run.trigger_type}</td>
                      <td className="px-4 py-3 text-slate-500">{timeAgo(run.created_at)}</td>
                      <td className="px-4 py-3 text-slate-500">{duration(seconds(run))}</td>
                      <td className="max-w-xs truncate px-4 py-3 text-xs text-rose-600">
                        {run.error}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        {runs.data && runs.data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between text-sm text-slate-600">
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, runs.data.total)} of {runs.data.total}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setParam("offset", String(Math.max(0, offset - PAGE_SIZE)))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={offset + PAGE_SIZE >= runs.data.total}
                onClick={() => setParam("offset", String(offset + PAGE_SIZE))}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export default function RunsPage() {
  return (
    <Suspense>
      <RunsContent />
    </Suspense>
  );
}
