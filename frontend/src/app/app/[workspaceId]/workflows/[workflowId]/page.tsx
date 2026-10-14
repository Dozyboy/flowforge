"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { ErrorState, PageLoader } from "@/components/ui/Feedback";
import { WorkflowEditor } from "@/features/editor/WorkflowEditor";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Credential, NodeTypeInfo, WorkflowDetail, WorkflowSummary } from "@/lib/types";

export default function WorkflowEditorPage() {
  const { workflowId } = useParams<{ workflowId: string }>();
  const { workspace } = useWorkspace();

  const workflow = useQuery({
    queryKey: queryKeys.workflow(workspace.id, workflowId),
    queryFn: () => api<WorkflowDetail>(`/workspaces/${workspace.id}/workflows/${workflowId}`),
    staleTime: Infinity,
  });
  const nodeTypes = useQuery({
    queryKey: queryKeys.nodeTypes,
    queryFn: () => api<NodeTypeInfo[]>("/node-types"),
    staleTime: Infinity,
  });
  const credentials = useQuery({
    queryKey: queryKeys.credentials(workspace.id),
    queryFn: () => api<Credential[]>(`/workspaces/${workspace.id}/credentials`),
  });
  const workflows = useQuery({
    queryKey: queryKeys.workflows(workspace.id),
    queryFn: () => api<WorkflowSummary[]>(`/workspaces/${workspace.id}/workflows`),
  });

  const error = workflow.error ?? nodeTypes.error;
  if (error) {
    return (
      <div className="p-4 sm:p-8">
        <ErrorState message={errorMessage(error)} />
      </div>
    );
  }
  if (!workflow.data || !nodeTypes.data) return <PageLoader />;

  return (
    <WorkflowEditor
      key={workflow.data.id}
      workflow={workflow.data}
      nodeTypes={nodeTypes.data}
      credentials={credentials.data ?? []}
      workflows={workflows.data ?? []}
    />
  );
}
