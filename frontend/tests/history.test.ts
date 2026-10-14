import { describe, expect, it } from "vitest";

import { historyReducer, type Snapshot } from "@/features/editor/use-graph-history";

const snap = (label: string): Snapshot => ({
  nodes: [
    {
      id: "n",
      type: "step",
      position: { x: 0, y: 0 },
      data: { nodeType: "log", label, config: {}, settings: {} },
    },
  ],
  edges: [],
});

const initial = { present: snap("a"), past: [], future: [], lastKey: null, lastAt: 0 };
const rename = (label: string) => () => snap(label);

describe("historyReducer", () => {
  it("records commits and undoes/redoes them", () => {
    let state = historyReducer(initial, { kind: "commit", update: rename("b"), at: 1 });
    state = historyReducer(state, { kind: "commit", update: rename("c"), at: 5000 });
    expect(state.past).toHaveLength(2);

    state = historyReducer(state, { kind: "undo" });
    expect(state.present.nodes[0].data.label).toBe("b");
    state = historyReducer(state, { kind: "redo" });
    expect(state.present.nodes[0].data.label).toBe("c");
  });

  it("coalesces rapid edits with the same key into one undo step", () => {
    let state = historyReducer(initial, {
      kind: "commit",
      update: rename("H"),
      key: "label",
      at: 0,
    });
    state = historyReducer(state, { kind: "commit", update: rename("He"), key: "label", at: 300 });
    state = historyReducer(state, { kind: "commit", update: rename("Hey"), key: "label", at: 600 });
    expect(state.past).toHaveLength(1);
    state = historyReducer(state, { kind: "undo" });
    expect(state.present.nodes[0].data.label).toBe("a");
  });

  it("a new commit clears the redo stack", () => {
    let state = historyReducer(initial, { kind: "commit", update: rename("b"), at: 0 });
    state = historyReducer(state, { kind: "undo" });
    state = historyReducer(state, { kind: "commit", update: rename("x"), at: 5000 });
    expect(state.future).toEqual([]);
  });

  it("replace changes state without history", () => {
    const state = historyReducer(initial, { kind: "replace", update: rename("moved") });
    expect(state.past).toEqual([]);
    expect(state.present.nodes[0].data.label).toBe("moved");
  });
});
