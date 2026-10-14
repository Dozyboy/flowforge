"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorState, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toaster";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { GraphDiff, Version, WorkflowDetail } from "@/lib/types";

export function TestRunModal({
  open,
  initialPayload,
  onClose,
  onStart,
  starting,
}: {
  open: boolean;
  initialPayload: unknown;
  onClose: () => void;
  onStart: (payload: Record<string, unknown>) => void;
  starting: boolean;
}) {
  const [text, setText] = useState(() => JSON.stringify(initialPayload, null, 2));
  const [error, setError] = useState<string | null>(null);

  const start = () => {
    try {
      const payload: unknown = JSON.parse(text || "{}");
      if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
        setError("The payload must be a JSON object");
        return;
      }
      onStart(payload as Record<string, unknown>);
    } catch {
      setError("Not valid JSON");
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Test run">
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          Runs the current draft with this payload as <code>{"{{ trigger }}"}</code>. Steps light up
          on the canvas as they execute. Emails and HTTP calls are real.
        </p>
        <Field label="Trigger payload (JSON)" htmlFor="test-payload">
          <Textarea
            id="test-payload"
            rows={10}
            className="font-mono text-xs"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setError(null);
            }}
          />
        </Field>
        {error && <ErrorState message={error} />}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={start} loading={starting}>
            Run
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export function PublishModal({
  open,
  onClose,
  onPublish,
  publishing,
}: {
  open: boolean;
  onClose: () => void;
  onPublish: (note: string) => void;
  publishing: boolean;
}) {
  const [note, setNote] = useState("");
  return (
    <Modal open={open} onClose={onClose} title="Publish a new version">
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          Triggers (webhook and schedule) always run the published version. You can roll back to any
          earlier version later.
        </p>
        <Field label="What changed? (optional)" htmlFor="publish-note">
          <Input
            id="publish-note"
            maxLength={300}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onPublish(note)} loading={publishing}>
            Publish
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export function SecretModal({
  secret,
  webhookUrl,
  onClose,
}: {
  secret: string | null;
  webhookUrl: string;
  onClose: () => void;
}) {
  const toast = useToast();
  const example = `curl -X POST ${webhookUrl} \\\n  -H "Content-Type: application/json" \\\n  -H "X-FlowForge-Secret: ${secret ?? ""}" \\\n  -d '{"message": "hello"}'`;
  return (
    <Modal open={secret !== null} onClose={onClose} title="Webhook secret">
      <div className="space-y-4 text-sm">
        <p className="rounded-md bg-amber-50 px-3 py-2 text-amber-900">
          Copy the secret now. It is stored hashed and cannot be shown again.
        </p>
        <div className="flex items-center gap-2">
          <code className="flex-1 overflow-x-auto rounded bg-slate-100 px-2 py-1.5 font-mono text-xs">
            {secret}
          </code>
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              void navigator.clipboard.writeText(secret ?? "").then(() => toast.success("Copied"))
            }
          >
            <Copy className="size-4" aria-hidden /> Copy
          </Button>
        </div>
        <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-xs text-slate-100">
          {example}
        </pre>
        <div className="flex justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    </Modal>
  );
}

function DiffSummary({ diff }: { diff: GraphDiff }) {
  const rows = [
    ["Added steps", diff.added_nodes.join(", ")],
    ["Removed steps", diff.removed_nodes.join(", ")],
    [
      "Changed steps",
      diff.changed_nodes
        .map(
          (c) => `${c.node_id}${c.config_fields.length ? ` (${c.config_fields.join(", ")})` : ""}`,
        )
        .join("; "),
    ],
    ["Added connections", diff.added_edges.join(", ")],
    ["Removed connections", diff.removed_edges.join(", ")],
  ].filter(([, value]) => value);
  if (!rows.length) return <p className="text-xs text-slate-500">Identical to the draft.</p>;
  return (
    <dl className="space-y-1 text-xs">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt className="inline font-medium text-slate-700">{label}: </dt>
          <dd className="inline text-slate-600">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function VersionsModal({
  open,
  workflowId,
  onClose,
  onRestored,
}: {
  open: boolean;
  workflowId: string;
  onClose: () => void;
  onRestored: (workflow: WorkflowDetail) => void;
}) {
  const { workspace, can } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [compare, setCompare] = useState<number | null>(null);
  const base = `/workspaces/${workspace.id}/workflows/${workflowId}`;
  const versions = useQuery({
    queryKey: queryKeys.versions(workspace.id, workflowId),
    queryFn: () => api<Version[]>(`${base}/versions`),
    enabled: open,
  });
  const diff = useQuery({
    queryKey: [...queryKeys.versions(workspace.id, workflowId), "diff", compare],
    queryFn: () => api<GraphDiff>(`${base}/versions/${compare}/diff`),
    enabled: open && compare !== null,
  });
  const restore = useMutation({
    mutationFn: (version: number) =>
      api<WorkflowDetail>(`${base}/versions/${version}/restore`, { method: "POST" }),
    onSuccess: (workflow, version) => {
      toast.success(`Version ${version} restored to the draft. Publish to make it live.`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflow(workspace.id, workflowId),
      });
      onRestored(workflow);
      onClose();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  return (
    <Modal open={open} onClose={onClose} title="Versions">
      {versions.isPending ? (
        <Spinner />
      ) : versions.data?.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing published yet.</p>
      ) : (
        <ul className="max-h-[60vh] space-y-2 overflow-y-auto">
          {versions.data?.map((version) => (
            <li key={version.id} className="rounded-md border border-slate-200 p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-slate-900">Version {version.version}</p>
                  <p className="text-xs text-slate-500">
                    {formatDateTime(version.created_at)}
                    {version.note && ` · ${version.note}`}
                  </p>
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setCompare(version.version)}>
                    Compare
                  </Button>
                  {can("member") && (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={restore.isPending && restore.variables === version.version}
                      onClick={() => restore.mutate(version.version)}
                    >
                      Restore
                    </Button>
                  )}
                </div>
              </div>
              {compare === version.version && (
                <div className="mt-2 border-t border-slate-100 pt-2">
                  {diff.data ? <DiffSummary diff={diff.data} /> : <Spinner />}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
