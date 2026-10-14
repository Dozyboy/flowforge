import { describe, expect, it } from "vitest";

import {
  defaultConfig,
  fromFlow,
  nextNodeId,
  outputHandles,
  pruneEdges,
  toFlow,
} from "@/features/editor/graph";
import type { NodeTypeInfo, WorkflowGraph } from "@/lib/types";

const classify: NodeTypeInfo = {
  type: "ai_classify",
  label: "AI classify",
  category: "ai",
  description: "",
  icon: "sparkles",
  config_schema: { type: "object", properties: { labels: { type: "array" } } },
  static_handles: [],
  dynamic_handles_key: "labels",
  dynamic_handles_extra: [],
};

const switchNode: NodeTypeInfo = {
  ...classify,
  type: "switch",
  dynamic_handles_key: "cases",
  dynamic_handles_extra: ["default"],
  config_schema: { type: "object", properties: { value: { type: "string", default: "x" } } },
};

const graph: WorkflowGraph = {
  nodes: [
    {
      id: "t",
      type: "trigger_manual",
      position: { x: 0, y: 0 },
      data: { label: "Start", config: {} },
    },
    {
      id: "c",
      type: "ai_classify",
      position: { x: 10.4, y: 120.6 },
      data: { label: "Classify", config: { labels: ["a", "b"] }, settings: { retries: 2 } },
    },
  ],
  edges: [
    { id: "e1", source: "t", target: "c" },
    { id: "e2", source: "c", target: "t", sourceHandle: "a" },
  ],
};

describe("toFlow / fromFlow", () => {
  it("round-trips the stored graph", () => {
    const { nodes, edges } = toFlow(graph);
    expect(nodes[1].type).toBe("step");
    expect(nodes[1].data.nodeType).toBe("ai_classify");
    const back = fromFlow(nodes, edges);
    expect(back.nodes[1].position).toEqual({ x: 10, y: 121 });
    expect(back.nodes[1].data.settings).toEqual({ retries: 2 });
    expect(back.nodes[0].data).not.toHaveProperty("settings");
    expect(back.edges).toEqual(graph.edges);
  });
});

describe("outputHandles", () => {
  it("derives handles from config", () => {
    expect(outputHandles(classify, { labels: ["refund", "bug", ""] })).toEqual(["refund", "bug"]);
    expect(outputHandles(switchNode, { cases: ["a"] })).toEqual(["a", "default"]);
    expect(outputHandles(undefined, {})).toEqual([]);
  });
});

describe("helpers", () => {
  it("creates identifier-safe unique node ids", () => {
    expect(nextNodeId("trigger_webhook", [])).toBe("webhook_1");
    expect(nextNodeId("ai_classify", ["ai_classify_1"])).toBe("ai_classify_2");
  });

  it("fills schema defaults", () => {
    expect(defaultConfig(switchNode)).toEqual({ value: "x" });
  });

  it("prunes edges whose branch disappeared", () => {
    const { nodes, edges } = toFlow(graph);
    nodes[1].data.config = { labels: ["b"] };
    const types = new Map([["ai_classify", classify]]);
    expect(pruneEdges(edges, nodes, types).map((e) => e.id)).toEqual(["e1"]);
  });
});
