"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FileUp, Plus, Workflow as WorkflowIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toaster";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Template, WorkflowDetail, WorkflowSummary } from "@/lib/types";

const TRIGGER_LABEL: Record<string, string> = {
  trigger_manual: "Manual",
  trigger_webhook: "Webhook",
  trigger_schedule: "Schedule",
};

function NewWorkflowModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { workspace, basePath } = useWorkspace();
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState("");
  const [templateId, setTemplateId] = useState<string | null>(null);
  const templates = useQuery({
    queryKey: queryKeys.templates,
    queryFn: () => api<Template[]>("/templates"),
    enabled: open,
  });
  const create = useMutation({
    mutationFn: () =>
      api<WorkflowDetail>(`/workspaces/${workspace.id}/workflows`, {
        method: "POST",
        body: { name: name || "Untitled workflow", template_id: templateId },
      }),
    onSuccess: (workflow) => router.push(`${basePath}/workflows/${workflow.id}`),
    onError: (err) => toast.error(errorMessage(err)),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Modal open={open} onClose={onClose} title="New workflow">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-2">
          <button
            type="button"
            onClick={() => setTemplateId(null)}
            className={cn(
              "rounded-md border p-3 text-left text-sm",
              templateId === null ? "border-indigo-500 bg-indigo-50" : "border-slate-200",
            )}
          >
            <span className="font-medium text-slate-900">Start from scratch</span>
          </button>
          {templates.data?.map((template) => (
            <button
              key={template.id}
              type="button"
              onClick={() => setTemplateId(template.id)}
              className={cn(
                "rounded-md border p-3 text-left text-sm",
                templateId === template.id ? "border-indigo-500 bg-indigo-50" : "border-slate-200",
              )}
            >
              <span className="flex items-center justify-between font-medium text-slate-900">
                {template.name}
                <Badge>{template.category}</Badge>
              </span>
              <span className="mt-1 block text-slate-500">{template.description}</span>
            </button>
          ))}
        </div>
        {templateId === null && (
          <Field label="Name" htmlFor="workflow-name">
            <Input
              id="workflow-name"
              maxLength={120}
              placeholder="Route new leads"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending}>
            Create workflow
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function ImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { workspace, basePath } = useWorkspace();
  const router = useRouter();
  const toast = useToast();
  const [text, setText] = useState("");
  const importWorkflow = useMutation({
    mutationFn: () => {
      let data: unknown;
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error("The file is not valid JSON");
      }
      return api<WorkflowDetail>(`/workspaces/${workspace.id}/workflows/import`, {
        method: "POST",
        body: { data },
      });
    },
    onSuccess: (workflow) => router.push(`${basePath}/workflows/${workflow.id}`),
    onError: (err) => toast.error(errorMessage(err)),
  });

  return (
    <Modal open={open} onClose={onClose} title="Import workflow">
      <div className="space-y-4">
        <input
          type="file"
          accept="application/json,.json"
          aria-label="Choose an exported workflow file"
          onChange={(e) => void e.target.files?.[0]?.text().then(setText)}
          className="text-sm"
        />
        <Field label="Or paste the exported JSON" htmlFor="import-json">
          <Textarea
            id="import-json"
            rows={8}
            className="font-mono text-xs"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => importWorkflow.mutate()}
            loading={importWorkflow.isPending}
            disabled={!text.trim()}
          >
            Import
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function WorkflowsContent() {
  const { workspace, basePath, can } = useWorkspace();
  const onboarding = useSearchParams().get("onboarding");
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const workflows = useQuery({
    queryKey: queryKeys.workflows(workspace.id),
    queryFn: () => api<WorkflowSummary[]>(`/workspaces/${workspace.id}/workflows`),
  });

  return (
    <>
      <PageHeader
        title="Workflows"
        description="Triggers, AI steps, logic and integrations, connected."
        actions={
          can("member") && (
            <>
              <Button variant="secondary" onClick={() => setImporting(true)}>
                <FileUp className="size-4" aria-hidden /> Import
              </Button>
              <Button onClick={() => setCreating(true)}>
                <Plus className="size-4" aria-hidden /> New workflow
              </Button>
            </>
          )
        }
      />
      <div className="space-y-4 p-4 sm:p-8">
        {onboarding && (
          <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-5 text-sm text-indigo-900">
            <p className="font-semibold">Welcome to FlowForge!</p>
            <p className="mt-1">
              Start from a template (support triage, lead qualification or a daily digest), press
              <strong> Test run</strong> to watch it execute, then <strong>Publish</strong> to turn
              on its trigger.
            </p>
          </div>
        )}
        {workflows.isError && <ErrorState message={errorMessage(workflows.error)} />}
        <Card className="overflow-hidden">
          {workflows.isPending ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : workflows.data?.length === 0 ? (
            <EmptyState
              icon={<WorkflowIcon className="size-5" />}
              title="No workflows yet"
              description="Create one from scratch or start from a template."
              action={
                can("member") && <Button onClick={() => setCreating(true)}>New workflow</Button>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm">
                <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                  <tr>
                    <th className="px-4 py-3">Workflow</th>
                    <th className="px-4 py-3">Trigger</th>
                    <th className="px-4 py-3">State</th>
                    <th className="px-4 py-3">Last run</th>
                    <th className="px-4 py-3 text-right">Runs (7d)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {workflows.data?.map((wf) => (
                    <tr key={wf.id} className="hover:bg-slate-50">
                      <td className="max-w-md px-4 py-3">
                        <Link
                          href={`${basePath}/workflows/${wf.id}`}
                          className="font-medium text-slate-900 hover:text-indigo-700"
                        >
                          {wf.name}
                        </Link>
                        {wf.description && (
                          <p className="truncate text-xs text-slate-500">{wf.description}</p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {wf.trigger_type
                          ? (TRIGGER_LABEL[wf.trigger_type] ?? wf.trigger_type)
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {wf.published_version === null ? (
                          <Badge>Draft</Badge>
                        ) : wf.is_active ? (
                          <Badge tone="success">Active · v{wf.published_version}</Badge>
                        ) : (
                          <Badge tone="warning">Paused · v{wf.published_version}</Badge>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {wf.last_run_status ? (
                          <span className="flex items-center gap-2">
                            <RunStatusBadge status={wf.last_run_status} />
                            <span className="text-xs text-slate-500">
                              {timeAgo(wf.last_run_at)}
                            </span>
                          </span>
                        ) : (
                          <span className="text-slate-400">Never</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-600">{wf.runs_last_7_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      <NewWorkflowModal open={creating} onClose={() => setCreating(false)} />
      <ImportModal open={importing} onClose={() => setImporting(false)} />
    </>
  );
}

export default function WorkflowsPage() {
  return (
    <Suspense>
      <WorkflowsContent />
    </Suspense>
  );
}
