"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Select } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toaster";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Invitation, Member, Role } from "@/lib/types";

const ROLES: { value: Role; label: string; description: string }[] = [
  { value: "viewer", label: "Viewer", description: "Read-only access" },
  { value: "member", label: "Member", description: "Build, run and publish workflows" },
  { value: "admin", label: "Admin", description: "Manage credentials, members and API keys" },
  { value: "owner", label: "Owner", description: "Full control, including deleting the workspace" },
];

function InviteForm() {
  const { workspace, can } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");

  const invite = useMutation({
    mutationFn: () =>
      api<Invitation>(`/workspaces/${workspace.id}/invitations`, {
        method: "POST",
        body: { email, role },
      }),
    onSuccess: () => {
      toast.success(`Invitation sent to ${email}`);
      setEmail("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.invitations(workspace.id) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    invite.mutate();
  };

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
      <Field label="Email address" htmlFor="invite-email">
        <Input
          id="invite-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </Field>
      <Field label="Role" htmlFor="invite-role">
        <Select id="invite-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.filter((r) => r.value !== "owner" || can("owner")).map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </Select>
      </Field>
      <Button type="submit" loading={invite.isPending}>
        Send invite
      </Button>
    </form>
  );
}

export default function MembersPage() {
  const { workspace, can } = useWorkspace();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const isAdmin = can("admin");

  const members = useQuery({
    queryKey: queryKeys.members(workspace.id),
    queryFn: () => api<Member[]>(`/workspaces/${workspace.id}/members`),
  });
  const invitations = useQuery({
    queryKey: queryKeys.invitations(workspace.id),
    queryFn: () => api<Invitation[]>(`/workspaces/${workspace.id}/invitations`),
    enabled: isAdmin,
  });

  const onError = (err: unknown) => toast.error(errorMessage(err));
  const refreshMembers = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.members(workspace.id) });

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: Role }) =>
      api(`/workspaces/${workspace.id}/members/${id}`, { method: "PATCH", body: { role } }),
    onSuccess: () => void refreshMembers(),
    onError,
  });
  const removeMember = useMutation({
    mutationFn: (id: string) =>
      api(`/workspaces/${workspace.id}/members/${id}`, { method: "DELETE" }),
    onSuccess: () => void refreshMembers(),
    onError,
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api(`/workspaces/${workspace.id}/invitations/${id}`, { method: "DELETE" }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.invitations(workspace.id) }),
    onError,
  });

  return (
    <div className="space-y-6">
      {isAdmin && (
        <Card>
          <CardHeader title="Invite a teammate" />
          <CardBody>
            <InviteForm />
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Members" />
        {members.isPending && (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        )}
        {members.isError && (
          <CardBody>
            <ErrorState message={errorMessage(members.error)} />
          </CardBody>
        )}
        <ul className="divide-y divide-slate-100">
          {members.data?.map((member) => {
            const isSelf = member.user.id === me?.user.id;
            const canManage = isAdmin && (member.role !== "owner" || can("owner"));
            return (
              <li key={member.id} className="flex flex-wrap items-center gap-4 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-slate-800">
                    {member.user.full_name}{" "}
                    {isSelf && <span className="text-slate-400">(you)</span>}
                  </p>
                  <p className="text-sm text-slate-500">{member.user.email}</p>
                </div>
                {canManage && !isSelf ? (
                  <Select
                    aria-label={`Role for ${member.user.full_name}`}
                    className="w-32"
                    value={member.role}
                    onChange={(e) =>
                      changeRole.mutate({ id: member.id, role: e.target.value as Role })
                    }
                  >
                    {ROLES.filter((r) => r.value !== "owner" || can("owner")).map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Badge>{member.role}</Badge>
                )}
                {(canManage || isSelf) && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      const message = isSelf
                        ? "Leave this workspace?"
                        : `Remove ${member.user.full_name}?`;
                      if (confirm(message)) removeMember.mutate(member.id);
                    }}
                  >
                    {isSelf ? "Leave" : "Remove"}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </Card>

      {isAdmin && invitations.data && invitations.data.length > 0 && (
        <Card>
          <CardHeader title="Pending invitations" />
          <ul className="divide-y divide-slate-100">
            {invitations.data.map((invitation) => (
              <li key={invitation.id} className="flex items-center gap-4 px-5 py-3 text-sm">
                <span className="flex-1 text-slate-800">{invitation.email}</span>
                <Badge>{invitation.role}</Badge>
                <span className="text-slate-500">sent {timeAgo(invitation.created_at)}</span>
                <Button size="sm" variant="ghost" onClick={() => revoke.mutate(invitation.id)}>
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <CardHeader title="Roles" />
        <CardBody>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            {ROLES.map((r) => (
              <div key={r.value}>
                <dt className="font-medium text-slate-800">{r.label}</dt>
                <dd className="text-slate-500">{r.description}</dd>
              </div>
            ))}
          </dl>
        </CardBody>
      </Card>
    </div>
  );
}
