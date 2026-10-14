"use client";

import type { Edge } from "@xyflow/react";
import { useCallback, useReducer } from "react";

import type { StepNode } from "@/features/editor/graph";

export interface Snapshot {
  nodes: StepNode[];
  edges: Edge[];
}

interface HistoryState {
  present: Snapshot;
  past: Snapshot[];
  future: Snapshot[];
  lastKey: string | null;
  lastAt: number;
}

type Action =
  | { kind: "commit"; update: (s: Snapshot) => Snapshot; key?: string; at: number }
  | { kind: "replace"; update: (s: Snapshot) => Snapshot }
  | { kind: "checkpoint" }
  | { kind: "undo" }
  | { kind: "redo" }
  | { kind: "reset"; snapshot: Snapshot };

const LIMIT = 100;
const COALESCE_MS = 1000;

export function historyReducer(state: HistoryState, action: Action): HistoryState {
  switch (action.kind) {
    case "commit": {
      const coalesce =
        action.key !== undefined &&
        state.lastKey === action.key &&
        action.at - state.lastAt < COALESCE_MS;
      return {
        present: action.update(state.present),
        past: coalesce ? state.past : [...state.past.slice(-LIMIT + 1), state.present],
        future: coalesce ? state.future : [],
        lastKey: action.key ?? null,
        lastAt: action.at,
      };
    }
    case "replace":
      return { ...state, present: action.update(state.present) };
    case "checkpoint":
      return {
        ...state,
        past: [...state.past.slice(-LIMIT + 1), state.present],
        future: [],
        lastKey: null,
      };
    case "undo": {
      const previous = state.past.at(-1);
      if (!previous) return state;
      return {
        present: previous,
        past: state.past.slice(0, -1),
        future: [state.present, ...state.future],
        lastKey: null,
        lastAt: 0,
      };
    }
    case "redo": {
      const [next, ...rest] = state.future;
      if (!next) return state;
      return {
        present: next,
        past: [...state.past, state.present],
        future: rest,
        lastKey: null,
        lastAt: 0,
      };
    }
    case "reset":
      return { present: action.snapshot, past: [], future: [], lastKey: null, lastAt: 0 };
  }
}

/**
 * Nodes and edges with undo/redo. Rapid edits with the same `coalesceKey` (typing in one field)
 * are merged into a single history entry.
 */
export function useGraphHistory(initial: Snapshot) {
  const [state, dispatch] = useReducer(historyReducer, {
    present: initial,
    past: [],
    future: [],
    lastKey: null,
    lastAt: 0,
  });

  const commit = useCallback(
    (update: (s: Snapshot) => Snapshot, key?: string) =>
      dispatch({ kind: "commit", update, key, at: Date.now() }),
    [],
  );
  const replace = useCallback(
    (update: (s: Snapshot) => Snapshot) => dispatch({ kind: "replace", update }),
    [],
  );
  const checkpoint = useCallback(() => dispatch({ kind: "checkpoint" }), []);
  const undo = useCallback(() => dispatch({ kind: "undo" }), []);
  const redo = useCallback(() => dispatch({ kind: "redo" }), []);
  const reset = useCallback((snapshot: Snapshot) => dispatch({ kind: "reset", snapshot }), []);

  return {
    nodes: state.present.nodes,
    edges: state.present.edges,
    commit,
    replace,
    checkpoint,
    undo,
    redo,
    reset,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}
