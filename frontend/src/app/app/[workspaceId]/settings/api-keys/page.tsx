"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toaster";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { timeAgo } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";

export default function ApiKeysPage() {
  const { workspace } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);

  const keys = useQuery({
    queryKey: queryKeys.apiKeys(workspace.id),
    queryFn: () => api<ApiKey[]>(`/workspaces/${workspace.id}/api-keys`),
  });
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys(workspace.id) });

  const create = useMutation({
    mutationFn: () =>
      api<ApiKeyCreated>(`/workspaces/${workspace.id}/api-keys`, {
        method: "POST",
        body: { name },
      }),
    onSuccess: (data) => {
      setCreated(data);
      setName("");
      void invalidate();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api(`/workspaces/${workspace.id}/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => void invalidate(),
    onError: (err) => toast.error(errorMessage(err)),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Create an API key"
          description="API keys can list workflows, start runs and read their results in this workspace. Send them as: Authorization: Bearer ff_…"
        />
        <CardBody className="space-y-4">
          <form onSubmit={submit} className="flex items-end gap-2">
            <Field label="Key name" htmlFor="key-name">
              <Input
                id="key-name"
                required
                maxLength={100}
                placeholder="CMS sync"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Button type="submit" loading={create.isPending}>
              Create key
            </Button>
          </form>
          {created && (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm">
              <p className="font-medium text-emerald-900">
                Copy your new key now. You will not be able to see it again.
              </p>
              <div className="mt-2 flex items-center gap-2">
                <code className="flex-1 overflow-x-auto rounded bg-white px-2 py-1.5 font-mono text-xs">
                  {created.key}
                </code>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(created.key)
                      .then(() => toast.success("Copied"))
                  }
                >
                  <Copy className="size-4" aria-hidden /> Copy
                </Button>
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Active keys" />
        {keys.data?.length === 0 ? (
          <EmptyState icon={<KeyRound className="size-5" />} title="No API keys" />
        ) : (
          <ul className="divide-y divide-slate-100">
            {keys.data?.map((key) => (
              <li key={key.id} className="flex items-center gap-4 px-5 py-3 text-sm">
                <div className="flex-1">
                  <p className="font-medium text-slate-800">{key.name}</p>
                  <p className="font-mono text-xs text-slate-500">{key.prefix}…</p>
                </div>
                <span className="text-slate-500">
                  {key.last_used_at ? `used ${timeAgo(key.last_used_at)}` : "never used"}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (confirm(`Revoke "${key.name}"? Integrations using it will stop working.`)) {
                      revoke.mutate(key.id);
                    }
                  }}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
