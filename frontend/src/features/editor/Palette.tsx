"use client";

import { useState } from "react";

import { Input } from "@/components/ui/Field";
import { CATEGORY_STYLE, NodeIcon } from "@/features/editor/NodeIcon";
import { cn } from "@/lib/cn";
import type { NodeTypeInfo } from "@/lib/types";

const ORDER = ["trigger", "ai", "logic", "data", "integration"];

export function Palette({
  types,
  hasTrigger,
  onAdd,
}: {
  types: NodeTypeInfo[];
  hasTrigger: boolean;
  onAdd: (type: NodeTypeInfo) => void;
}) {
  const [search, setSearch] = useState("");
  const query = search.trim().toLowerCase();
  const visible = types.filter(
    (t) =>
      !query ||
      t.label.toLowerCase().includes(query) ||
      t.description.toLowerCase().includes(query),
  );

  return (
    <aside
      className="hidden h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex"
      aria-label="Steps"
    >
      <div className="border-b border-slate-100 p-3">
        <Input
          aria-label="Search steps"
          placeholder="Search steps"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        {ORDER.map((category) => {
          const items = visible.filter((t) => t.category === category);
          if (!items.length) return null;
          return (
            <div key={category}>
              <p className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                {CATEGORY_STYLE[category].label}
              </p>
              <div className="space-y-1">
                {items.map((type) => {
                  const disabled = category === "trigger" && hasTrigger;
                  return (
                    <button
                      key={type.type}
                      type="button"
                      disabled={disabled}
                      onClick={() => onAdd(type)}
                      title={disabled ? "A workflow has exactly one trigger" : type.description}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <span
                        className={cn(
                          "flex size-6 shrink-0 items-center justify-center rounded",
                          CATEGORY_STYLE[category].color,
                        )}
                      >
                        <NodeIcon name={type.icon} className="size-3.5" />
                      </span>
                      <span className="text-slate-700">{type.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
