/**
 * Pure helpers that convert between the stored workflow JSON and React Flow state.
 * Kept free of React so they are easy to unit test (tests/graph.test.ts).
 */
import type { Edge, Node } from "@xyflow/react";

import type { GraphEdge, GraphNode, NodeTypeInfo, StepSettings, WorkflowGraph } from "@/lib/types";

export interface StepData extends Record<string, unknown> {
  nodeType: string;
  label: string;
  config: Record<string, unknown>;
  settings: StepSettings;
}

export type StepNode = Node<StepData, "step">;

export function toFlow(graph: WorkflowGraph): { nodes: StepNode[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      type: "step",
      position: node.position ?? { x: 0, y: 0 },
      data: {
        nodeType: node.type,
        label: node.data?.label ?? node.id,
        config: node.data?.config ?? {},
        settings: node.data?.settings ?? {},
      },
    })),
    edges: graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle ?? null,
      label: edge.sourceHandle ?? undefined,
    })),
  };
}

export function fromFlow(nodes: StepNode[], edges: Edge[]): WorkflowGraph {
  return {
    nodes: nodes.map((node): GraphNode => ({
      id: node.id,
      type: node.data.nodeType,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      data: {
        label: node.data.label,
        config: node.data.config,
        ...(Object.keys(node.data.settings).length ? { settings: node.data.settings } : {}),
      },
    })),
    edges: edges.map((edge): GraphEdge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
    })),
  };
}

/** Output handles of a node; an empty list means a single unnamed output. */
export function outputHandles(
  info: NodeTypeInfo | undefined,
  config: Record<string, unknown>,
): string[] {
  if (!info) return [];
  const handles = [...info.static_handles];
  if (info.dynamic_handles_key) {
    const values = config[info.dynamic_handles_key];
    if (Array.isArray(values)) {
      handles.push(...values.filter((v): v is string => typeof v === "string" && v.length > 0));
    }
    handles.push(...info.dynamic_handles_extra);
  }
  return [...new Set(handles)];
}

/** Node ids are used in expressions ({{ steps.<id>.output }}), so they must be identifiers. */
export function nextNodeId(type: string, existing: Iterable<string>): string {
  const taken = new Set(existing);
  const base = type.replace(/^trigger_/, "").replace(/[^A-Za-z0-9_]/g, "_");
  for (let i = 1; ; i += 1) {
    const candidate = `${base}_${i}`;
    if (!taken.has(candidate)) return candidate;
  }
}

export function defaultConfig(info: NodeTypeInfo): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const [key, schema] of Object.entries(info.config_schema.properties ?? {})) {
    if (schema.default !== undefined) config[key] = schema.default;
  }
  return config;
}

/** Remove edges whose branch no longer exists (e.g. after deleting a classifier label). */
export function pruneEdges(
  edges: Edge[],
  nodes: StepNode[],
  types: Map<string, NodeTypeInfo>,
): Edge[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return edges.filter((edge) => {
    const source = byId.get(edge.source);
    if (!source || !byId.has(edge.target)) return false;
    const handles = outputHandles(types.get(source.data.nodeType), source.data.config);
    return handles.length === 0 ? !edge.sourceHandle : handles.includes(edge.sourceHandle ?? "");
  });
}
