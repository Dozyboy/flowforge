"use client";

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  History,
  KeyRound,
  Play,
  Redo2,
  Rocket,
  Save,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toaster";
import { ConfigPanel } from "@/features/editor/ConfigPanel";
import { PublishModal, SecretModal, TestRunModal, VersionsModal } from "@/features/editor/dialogs";
import { EditorContext } from "@/features/editor/editor-context";
import {
  defaultConfig,
  fromFlow,
  nextNodeId,
  pruneEdges,
  toFlow,
  type StepNode,
} from "@/features/editor/graph";
import { Palette } from "@/features/editor/Palette";
import { RunPanel } from "@/features/editor/RunPanel";
import { StepNodeView } from "@/features/editor/StepNodeView";
import { useGraphHistory } from "@/features/editor/use-graph-history";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { ApiError, api, errorMessage } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useDocumentTitle } from "@/lib/use-document-title";
import { liveRunEvents } from "@/lib/run-events";
import type {
  Credential,
  GraphIssue,
  NodeTypeInfo,
  PublishResult,
  RunDetail,
  RunSummary,
  SaveResult,
  StepStatus,
  WorkflowDetail,
  WorkflowGraph,
  WorkflowSummary,
} from "@/lib/types";

const NODE_TYPES = { step: StepNodeView };

interface EditorProps {
  workflow: WorkflowDetail;
  nodeTypes: NodeTypeInfo[];
  credentials: Credential[];
  workflows: WorkflowSummary[];
}

/** Normalised JSON used to detect unsaved changes (same shape the save request sends). */
function serialize(name: string, stored: WorkflowGraph): string {
  const { nodes, edges } = toFlow(stored);
  return JSON.stringify({ name, graph: fromFlow(nodes, edges) });
}

function samplePayload(workflow: WorkflowDetail): unknown {
  const trigger = workflow.draft_graph.nodes.find((n) => n.type.startsWith("trigger_"));
  if (trigger?.type === "trigger_manual") return trigger.data.config.sample_payload ?? {};
  if (trigger?.type === "trigger_webhook")
    return { body: { message: "Hello" }, query: {}, headers: {} };
  return {};
}

function EditorCanvas({ workflow: initial, nodeTypes, credentials, workflows }: EditorProps) {
  const { workspace, basePath, can } = useWorkspace();
  const queryClient = useQueryClient();
  const toast = useToast();
  const flow = useReactFlow();
  const canvasRef = useRef<HTMLDivElement>(null);
  const readOnly = !can("member");

  const types = useMemo(() => new Map(nodeTypes.map((t) => [t.type, t])), [nodeTypes]);
  const history = useGraphHistory(toFlow(initial.draft_graph));
  const { nodes, edges, commit, replace, checkpoint, undo, redo } = history;

  const [name, setName] = useState(initial.name);
  useDocumentTitle(name || "Workflow");
  const [savedJson, setSavedJson] = useState(() => serialize(initial.name, initial.draft_graph));
  const [issues, setIssues] = useState<GraphIssue[]>(initial.issues);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [publishedVersion, setPublishedVersion] = useState(initial.published_version);
  const [isActive, setIsActive] = useState(initial.is_active);

  const graph = useMemo(() => fromFlow(nodes, edges), [nodes, edges]);
  const currentJson = JSON.stringify({ name, graph });
  const dirty = currentJson !== savedJson;
  const base = `/workspaces/${workspace.id}/workflows/${initial.id}`;

  const issuesByNode = useMemo(() => {
    const map = new Map<string, string[]>();
    issues.forEach((issue) => {
      if (issue.node_id) map.set(issue.node_id, [...(map.get(issue.node_id) ?? []), issue.message]);
    });
    return map;
  }, [issues]);
  const globalIssues = issues.filter((i) => !i.node_id);

  // --- live test run ------------------------------------------------------------------------
  const run = useQuery({
    queryKey: queryKeys.run(workspace.id, runId ?? "none"),
    queryFn: () => api<RunDetail>(`/workspaces/${workspace.id}/runs/${runId}`),
    enabled: runId !== null,
    refetchInterval: (query) =>
      query.state.data && ["succeeded", "failed", "cancelled"].includes(query.state.data.status)
        ? false
        : 3000,
  });
  useEffect(
    () =>
      liveRunEvents.subscribe((event) => {
        if (runId && String(event.data.run_id ?? event.data.id) === runId) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.run(workspace.id, runId) });
        }
      }),
    [queryClient, runId, workspace.id],
  );
  const liveStatus = useMemo(
    () => new Map<string, StepStatus>(run.data?.steps.map((s) => [s.node_id, s.status]) ?? []),
    [run.data],
  );

  // --- mutations ----------------------------------------------------------------------------
  const save = useMutation({
    // Remember exactly what was sent: edits made while the request is in flight stay unsaved.
    mutationFn: async () => {
      const sent = currentJson;
      const result = await api<SaveResult>(base, { method: "PATCH", body: { name, graph } });
      return { result, sent };
    },
    onSuccess: ({ result, sent }) => {
      setIssues(result.issues);
      setSavedJson(sent);
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflows(workspace.id) });
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const saveIfDirty = async () => {
    if (dirty) await save.mutateAsync();
  };

  const publish = useMutation({
    mutationFn: async (note: string) => {
      await saveIfDirty();
      return api<PublishResult>(`${base}/publish`, { method: "POST", body: { note } });
    },
    onSuccess: (result) => {
      setPublishOpen(false);
      setPublishedVersion(result.version);
      setIsActive(true);
      toast.success(`Version ${result.version} is live`);
      if (result.webhook_secret) setSecret(result.webhook_secret);
      void queryClient.invalidateQueries({ queryKey: queryKeys.workflows(workspace.id) });
    },
    onError: (err) => {
      setPublishOpen(false);
      if (err instanceof ApiError && err.code === "workflow_invalid") {
        toast.error("Fix the highlighted problems before publishing");
      } else {
        toast.error(errorMessage(err));
      }
    },
  });

  const testRun = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      await saveIfDirty();
      return api<RunSummary>(`${base}/runs`, {
        method: "POST",
        body: { payload, use_draft: true },
      });
    },
    onSuccess: (started) => {
      setTestOpen(false);
      setRunId(started.id);
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const activation = useMutation({
    mutationFn: (active: boolean) =>
      api(`${base}/activation`, { method: "POST", body: { active } }),
    onSuccess: (_, active) => {
      setIsActive(active);
      toast.success(active ? "Triggers are on" : "Triggers are paused");
    },
    onError: (err) => toast.error(errorMessage(err)),
  });

  const rotateSecret = useMutation({
    mutationFn: () => api<{ webhook_secret: string }>(`${base}/webhook-secret`, { method: "POST" }),
    onSuccess: (data) => setSecret(data.webhook_secret),
    onError: (err) => toast.error(errorMessage(err)),
  });

  const exportJson = async () => {
    const data = await api<unknown>(`${base}/export`);
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "workflow"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // --- graph editing ------------------------------------------------------------------------
  const onNodesChange = useCallback(
    (changes: NodeChange<StepNode>[]) => {
      const structural = changes.some((c) => c.type === "remove" || c.type === "add");
      const apply = (s: { nodes: StepNode[]; edges: Edge[] }) => {
        const nextNodes = applyNodeChanges(changes, s.nodes);
        return {
          nodes: nextNodes,
          edges: structural ? pruneEdges(s.edges, nextNodes, types) : s.edges,
        };
      };
      if (structural) commit(apply);
      else replace(apply);
    },
    [commit, replace, types],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const apply = (s: { nodes: StepNode[]; edges: Edge[] }) => ({
        nodes: s.nodes,
        edges: applyEdgeChanges(changes, s.edges),
      });
      if (changes.some((c) => c.type === "remove")) commit(apply);
      else replace(apply);
    },
    [commit, replace],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (connection.source === connection.target) return;
      commit((s) => {
        const duplicate = s.edges.some(
          (e) =>
            e.source === connection.source &&
            e.target === connection.target &&
            (e.sourceHandle ?? null) === (connection.sourceHandle ?? null),
        );
        if (duplicate) return s;
        const edge: Edge = {
          id: `e_${connection.source}_${connection.sourceHandle ?? "out"}_${connection.target}`,
          source: connection.source,
          target: connection.target,
          sourceHandle: connection.sourceHandle,
          label: connection.sourceHandle ?? undefined,
        };
        return { nodes: s.nodes, edges: [...s.edges, edge] };
      });
    },
    [commit],
  );

  const addNode = (info: NodeTypeInfo) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    const center = flow.screenToFlowPosition({
      x: (rect?.left ?? 0) + (rect?.width ?? 800) / 2,
      y: (rect?.top ?? 0) + (rect?.height ?? 600) / 3,
    });
    const id = nextNodeId(
      info.type,
      nodes.map((n) => n.id),
    );
    const node: StepNode = {
      id,
      type: "step",
      position: { x: center.x - 120 + nodes.length * 8, y: center.y + nodes.length * 8 },
      data: { nodeType: info.type, label: info.label, config: defaultConfig(info), settings: {} },
    };
    commit((s) => ({
      nodes: [...s.nodes.map((n) => ({ ...n, selected: false })), { ...node, selected: true }],
      edges: s.edges,
    }));
    setSelectedId(id);
  };

  const updateSelected = (patch: Partial<StepNode["data"]>, coalesceKey: string) => {
    if (!selectedId) return;
    commit((s) => {
      const nextNodes = s.nodes.map((n) =>
        n.id === selectedId ? { ...n, data: { ...n.data, ...patch } } : n,
      );
      return { nodes: nextNodes, edges: pruneEdges(s.edges, nextNodes, types) };
    }, coalesceKey);
  };

  const deleteSelected = () => {
    if (!selectedId) return;
    commit((s) => {
      const nextNodes = s.nodes.filter((n) => n.id !== selectedId);
      return { nodes: nextNodes, edges: pruneEdges(s.edges, nextNodes, types) };
    });
    setSelectedId(null);
  };

  // --- keyboard shortcuts -------------------------------------------------------------------
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (!mod) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        if (!readOnly) save.mutate();
      } else if (key === "z" && !event.shiftKey) {
        const target = event.target as HTMLElement;
        if (target.closest("input, textarea")) return;
        event.preventDefault();
        undo();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [readOnly, redo, save, undo]);

  const selected = nodes.find((n) => n.id === selectedId);
  const hasTrigger = nodes.some((n) => n.data.nodeType.startsWith("trigger_"));

  return (
    <EditorContext.Provider
      value={{
        types,
        credentials,
        workflows,
        currentWorkflowId: initial.id,
        issuesByNode,
        liveStatus,
        readOnly,
      }}
    >
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-4 py-2.5">
          <Link
            href={`${basePath}/workflows`}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100"
            aria-label="Back to workflows"
          >
            <ArrowLeft className="size-4" />
          </Link>
          <input
            aria-label="Workflow name"
            value={name}
            disabled={readOnly}
            onChange={(e) => setName(e.target.value)}
            className="min-w-48 rounded px-2 py-1 text-base font-semibold text-slate-900 hover:bg-slate-50 focus:bg-white focus:ring-2 focus:ring-indigo-500/20 focus:outline-none"
          />
          {publishedVersion === null ? (
            <Badge>Draft</Badge>
          ) : (
            <button
              type="button"
              disabled={readOnly || activation.isPending}
              onClick={() => activation.mutate(!isActive)}
              title={isActive ? "Click to pause triggers" : "Click to turn triggers on"}
            >
              <Badge tone={isActive ? "success" : "warning"}>
                {isActive ? "Active" : "Paused"} · v{publishedVersion}
              </Badge>
            </button>
          )}
          <span className="text-xs text-slate-500" aria-live="polite">
            {save.isPending ? "Saving…" : dirty ? "Unsaved changes" : "All changes saved"}
          </span>

          <div className="ml-auto flex flex-wrap items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={undo}
              disabled={!history.canUndo}
              aria-label="Undo"
            >
              <Undo2 className="size-4" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={redo}
              disabled={!history.canRedo}
              aria-label="Redo"
            >
              <Redo2 className="size-4" />
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setVersionsOpen(true)}>
              <History className="size-4" aria-hidden /> Versions
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void exportJson()}>
              <Download className="size-4" aria-hidden /> Export
            </Button>
            {can("admin") && initial.has_webhook_secret && (
              <Button size="sm" variant="ghost" onClick={() => rotateSecret.mutate()}>
                <KeyRound className="size-4" aria-hidden /> Rotate secret
              </Button>
            )}
            {!readOnly && (
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => save.mutate()}
                  loading={save.isPending}
                  disabled={!dirty}
                >
                  <Save className="size-4" aria-hidden /> Save
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setTestOpen(true)}>
                  <Play className="size-4" aria-hidden /> Test run
                </Button>
                <Button size="sm" onClick={() => setPublishOpen(true)}>
                  <Rocket className="size-4" aria-hidden /> Publish
                </Button>
              </>
            )}
          </div>
        </header>

        <p className="border-b border-indigo-100 bg-indigo-50 px-4 py-2 text-xs text-indigo-900 md:hidden">
          Adding steps needs a larger screen. Here you can review the flow, test-run and publish.
        </p>
        {globalIssues.length > 0 && (
          <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
            {globalIssues.map((i) => i.message).join(" · ")}
          </div>
        )}

        <div className="relative flex min-h-0 flex-1">
          {!readOnly && <Palette types={nodeTypes} hasTrigger={hasTrigger} onAdd={addNode} />}
          <div ref={canvasRef} className="relative min-w-0 flex-1 bg-slate-50">
            <ReactFlow<StepNode>
              nodes={nodes}
              edges={edges}
              nodeTypes={NODE_TYPES}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeDragStart={checkpoint}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              onPaneClick={() => setSelectedId(null)}
              nodesDraggable={!readOnly}
              nodesConnectable={!readOnly}
              elementsSelectable
              deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
              fitView
              fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={16} />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable className="!bg-white max-md:!hidden" />
            </ReactFlow>
            {nodes.length === 0 && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <p className="rounded-md bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
                  Pick a trigger from the left to start.
                </p>
              </div>
            )}
            {run.data && (
              <RunPanel
                run={run.data}
                onSelectNode={setSelectedId}
                onClose={() => setRunId(null)}
              />
            )}
          </div>
          {selected && (
            <ConfigPanel
              key={selected.id}
              node={selected}
              webhookUrl={initial.webhook_url}
              lastStep={run.data?.steps.find((s) => s.node_id === selected.id)}
              onChange={updateSelected}
              onDelete={deleteSelected}
              onClose={() => setSelectedId(null)}
            />
          )}
        </div>
      </div>

      {testOpen && (
        <TestRunModal
          open={testOpen}
          initialPayload={samplePayload(initial)}
          onClose={() => setTestOpen(false)}
          onStart={(payload) => testRun.mutate(payload)}
          starting={testRun.isPending}
        />
      )}
      <PublishModal
        open={publishOpen}
        onClose={() => setPublishOpen(false)}
        onPublish={(note) => publish.mutate(note)}
        publishing={publish.isPending}
      />
      <VersionsModal
        open={versionsOpen}
        workflowId={initial.id}
        onClose={() => setVersionsOpen(false)}
        onRestored={(workflow) => {
          history.reset(toFlow(workflow.draft_graph));
          setIssues(workflow.issues);
          setSavedJson(serialize(name, workflow.draft_graph));
        }}
      />
      <SecretModal
        secret={secret}
        webhookUrl={initial.webhook_url}
        onClose={() => setSecret(null)}
      />
    </EditorContext.Provider>
  );
}

export function WorkflowEditor(props: EditorProps) {
  return (
    <ReactFlowProvider>
      <EditorCanvas {...props} />
    </ReactFlowProvider>
  );
}
