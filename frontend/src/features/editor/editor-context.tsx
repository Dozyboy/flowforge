"use client";

import { createContext, useContext } from "react";

import type { Credential, NodeTypeInfo, StepStatus, WorkflowSummary } from "@/lib/types";

export interface EditorContextValue {
  types: Map<string, NodeTypeInfo>;
  credentials: Credential[];
  workflows: WorkflowSummary[];
  currentWorkflowId: string;
  issuesByNode: Map<string, string[]>;
  liveStatus: Map<string, StepStatus>;
  readOnly: boolean;
}

export const EditorContext = createContext<EditorContextValue | null>(null);

export function useEditor(): EditorContextValue {
  const context = useContext(EditorContext);
  if (!context) throw new Error("useEditor must be used inside the workflow editor");
  return context;
}
