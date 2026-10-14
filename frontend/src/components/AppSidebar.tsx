"use client";

import { useQuery } from "@tanstack/react-query";
import {
  X,
  ChevronsUpDown,
  History,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Plus,
  Settings,
  UserCheck,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/Logo";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { initials } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { ConnectionState } from "@/lib/realtime";
import type { PendingApproval } from "@/lib/types";

const NAV = [
  { href: "", label: "Dashboard", icon: LayoutDashboard },
  { href: "/workflows", label: "Workflows", icon: Workflow },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/approvals", label: "Approvals", icon: UserCheck },
  { href: "/credentials", label: "Credentials", icon: KeyRound },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppSidebar({
  connection,
  open = false,
  onClose,
}: {
  connection: ConnectionState;
  /** Small screens only: whether the off-canvas sidebar is shown. */
  open?: boolean;
  onClose?: () => void;
}) {
  const { workspace, basePath } = useWorkspace();
  const { me, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [switcherOpen, setSwitcherOpen] = useState(false);

  const approvals = useQuery({
    queryKey: queryKeys.approvals(workspace.id),
    queryFn: () => api<PendingApproval[]>(`/workspaces/${workspace.id}/approvals`),
  });
  const waiting = approvals.data?.length ?? 0;

  const isActive = (href: string) =>
    href === "" ? pathname === basePath : pathname.startsWith(`${basePath}${href}`);

  return (
    <aside
      id="app-sidebar"
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white transition-transform duration-200 lg:static lg:w-60 lg:translate-x-0",
        open ? "translate-x-0 shadow-xl" : "-translate-x-full",
      )}
    >
      <div className="flex items-center justify-between px-4 py-4">
        <Logo href="/app" />
        <button
          type="button"
          onClick={onClose}
          aria-label="Close menu"
          className="rounded p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="relative px-3">
        <button
          type="button"
          onClick={() => setSwitcherOpen((open) => !open)}
          className="flex w-full items-center justify-between rounded-md border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50"
          aria-expanded={switcherOpen}
        >
          <span className="truncate font-medium text-slate-800">{workspace.name}</span>
          <ChevronsUpDown className="size-4 text-slate-400" aria-hidden />
        </button>
        {switcherOpen && (
          <div className="absolute inset-x-3 top-full z-20 mt-1 rounded-md border border-slate-200 bg-white py-1 shadow-lg">
            {me?.workspaces.map((ws) => (
              <button
                key={ws.id}
                type="button"
                onClick={() => {
                  setSwitcherOpen(false);
                  router.push(`/app/${ws.id}`);
                }}
                className={cn(
                  "block w-full truncate px-3 py-2 text-left text-sm hover:bg-slate-50",
                  ws.id === workspace.id && "font-medium text-indigo-700",
                )}
              >
                {ws.name}
              </button>
            ))}
            <Link
              href="/app/new"
              className="flex items-center gap-2 border-t border-slate-100 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              <Plus className="size-4" aria-hidden /> New workspace
            </Link>
          </div>
        )}
      </div>

      <nav className="mt-4 flex-1 space-y-0.5 px-3" aria-label="Main">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={`${basePath}${href}`}
            aria-current={isActive(href) ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium",
              isActive(href)
                ? "bg-indigo-50 text-indigo-700"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
            )}
          >
            <Icon className="size-4" aria-hidden />
            <span className="flex-1">{label}</span>
            {href === "/approvals" && waiting > 0 && (
              <span className="rounded-full bg-amber-500 px-1.5 text-xs font-semibold text-white">
                {waiting}
              </span>
            )}
          </Link>
        ))}
      </nav>

      <div className="border-t border-slate-100 p-3">
        <div className="flex items-center gap-2 px-1 pb-2 text-xs text-slate-500">
          <span
            className={cn(
              "size-2 rounded-full",
              connection === "open" ? "bg-emerald-500" : "bg-amber-400",
            )}
            aria-hidden
          />
          {connection === "open" ? "Live updates on" : "Reconnecting…"}
        </div>
        <div className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">
            {initials(me?.user.full_name)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800">{me?.user.full_name}</p>
            <p className="truncate text-xs text-slate-500">{workspace.role}</p>
          </div>
          <button
            type="button"
            onClick={() => void logout().then(() => router.replace("/login"))}
            className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </aside>
  );
}
