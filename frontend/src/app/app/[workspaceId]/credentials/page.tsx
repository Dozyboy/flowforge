"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toaster";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { timeAgo } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Credential, CredentialType } from "@/lib/types";

function CredentialModal({
  open,
  types,
  editing,
  onClose,
}: {
  open: boolean;
  types: CredentialType[];
  editing: Credential | null;
  onClose: () => void;
}) {
  const { workspace } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(editing?.name ?? "");
  const [typeName, setTypeName] = useState(editing?.type ?? types[0]?.type ?? "");
  const [data, setData] = useState<Record<string, string>>({});
  const type = types.find((t) => t.type === typeName);

  const save = useMutation({
    mutationFn: () =>
      editing
        ? api(`/workspaces/${workspace.id}/credentials/${editing.id}`, {
            method: "PATCH",
            body: { name, data: Object.keys(data).length ? data : undefined },
          })
        : api(`/workspaces/${workspace.id}/credentials`, {
            method: "POST",
            body: { name, type: typeName, data },
          }),
    onSuccess: () => {
      toast.success(editing ? "Credential updated" : "Credential saved");
      void queryClient.invalidateQueries({ queryKey: queryKeys.credentials(workspace.id) });
      onClose();
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? `Edit ${editing.name}` : "New credential"}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name" htmlFor="cred-name" hint="Shown when choosing a credential in a step">
          <Input
            id="cred-name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        {!editing && (
          <Field label="Type" htmlFor="cred-type" hint={type?.description}>
            <Select
              id="cred-type"
              value={typeName}
              onChange={(e) => {
                setTypeName(e.target.value);
                setData({});
              }}
            >
              {types.map((t) => (
                <option key={t.type} value={t.type}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {editing && (
          <p className="text-xs text-slate-500">
            Saved secrets are never shown. Fill in the fields below only to replace them.
          </p>
        )}
        {type?.fields.map((field) => (
          <Field key={field.name} label={field.label} htmlFor={`cred-${field.name}`}>
            {field.multiline ? (
              <Textarea
                id={`cred-${field.name}`}
                rows={6}
                className="font-mono text-xs"
                required={!editing}
                value={data[field.name] ?? ""}
                onChange={(e) => setData({ ...data, [field.name]: e.target.value })}
              />
            ) : (
              <Input
                id={`cred-${field.name}`}
                type={field.secret ? "password" : "text"}
                autoComplete="off"
                required={!editing}
                value={data[field.name] ?? ""}
                onChange={(e) => setData({ ...data, [field.name]: e.target.value })}
              />
            )}
          </Field>
        ))}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function CredentialsPage() {
  const { workspace, can } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [modal, setModal] = useState<{ editing: Credential | null } | null>(null);
  const credentials = useQuery({
    queryKey: queryKeys.credentials(workspace.id),
    queryFn: () => api<Credential[]>(`/workspaces/${workspace.id}/credentials`),
  });
  const types = useQuery({
    queryKey: queryKeys.credentialTypes,
    queryFn: () => api<CredentialType[]>("/credential-types"),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      api(`/workspaces/${workspace.id}/credentials/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.credentials(workspace.id) }),
    onError: (err) => toast.error(errorMessage(err)),
  });
  const typeLabel = new Map(types.data?.map((t) => [t.type, t.label]));

  return (
    <>
      <PageHeader
        title="Credentials"
        description="Secrets for integrations, encrypted at rest. Steps reference them by name; values are never shown again."
        actions={
          can("admin") && (
            <Button onClick={() => setModal({ editing: null })} disabled={!types.data}>
              <Plus className="size-4" aria-hidden /> New credential
            </Button>
          )
        }
      />
      <div className="p-4 sm:p-8">
        {credentials.isError && <ErrorState message={errorMessage(credentials.error)} />}
        <Card>
          {credentials.isPending ? (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          ) : credentials.data?.length === 0 ? (
            <EmptyState
              icon={<KeyRound className="size-5" />}
              title="No credentials yet"
              description="Add a Slack webhook, Telegram bot, API token or Google service account."
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {credentials.data?.map((credential) => (
                <li key={credential.id} className="flex items-center gap-4 px-5 py-3 text-sm">
                  <KeyRound className="size-4 text-slate-400" aria-hidden />
                  <span className="flex-1 font-medium text-slate-800">{credential.name}</span>
                  <Badge>{typeLabel.get(credential.type) ?? credential.type}</Badge>
                  <span className="text-xs text-slate-500">
                    updated {timeAgo(credential.updated_at)}
                  </span>
                  {can("admin") && (
                    <>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setModal({ editing: credential })}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Delete ${credential.name}`}
                        onClick={() => {
                          if (confirm(`Delete "${credential.name}"? Steps using it will fail.`)) {
                            remove.mutate(credential.id);
                          }
                        }}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {modal && types.data && (
        <CredentialModal
          open
          types={types.data}
          editing={modal.editing}
          onClose={() => setModal(null)}
        />
      )}
    </>
  );
}
