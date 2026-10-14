"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toaster";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

export default function GeneralSettingsPage() {
  const { workspace, can } = useWorkspace();
  const { reload } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState(workspace.name);

  const rename = useMutation({
    mutationFn: () => api(`/workspaces/${workspace.id}`, { method: "PATCH", body: { name } }),
    onSuccess: () => {
      void reload();
      toast.success("Workspace renamed");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: () => api(`/workspaces/${workspace.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await reload();
      router.replace("/app");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    rename.mutate();
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Workspace" />
        <CardBody>
          <form onSubmit={submit} className="max-w-md space-y-4">
            <Field label="Name" htmlFor="workspace-name">
              <Input
                id="workspace-name"
                maxLength={120}
                disabled={!can("admin")}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Workspace ID" htmlFor="workspace-id" hint="Used in API URLs">
              <Input id="workspace-id" readOnly value={workspace.id} className="font-mono" />
            </Field>
            {can("admin") && (
              <Button type="submit" loading={rename.isPending} disabled={!name.trim()}>
                Save
              </Button>
            )}
          </form>
        </CardBody>
      </Card>
      {can("owner") && (
        <Card className="border-rose-200">
          <CardHeader
            title="Delete workspace"
            description="Deletes all workflows, versions, runs and credentials. This cannot be undone."
          />
          <CardBody>
            <Button
              variant="danger"
              loading={remove.isPending}
              onClick={() => {
                if (prompt(`Type "${workspace.name}" to confirm`) === workspace.name)
                  remove.mutate();
              }}
            >
              Delete workspace
            </Button>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
