"use client";

import { createContext, useContext, type ReactNode } from "react";

import { hasRole } from "@/lib/format";
import type { Role, WorkspaceSummary } from "@/lib/types";

interface WorkspaceContextValue {
  workspace: WorkspaceSummary;
  basePath: string;
  can: (minimum: Role) => boolean;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({
  workspace,
  children,
}: {
  workspace: WorkspaceSummary;
  children: ReactNode;
}) {
  const value: WorkspaceContextValue = {
    workspace,
    basePath: `/app/${workspace.id}`,
    can: (minimum) => hasRole(workspace.role, minimum),
  };
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return context;
}
