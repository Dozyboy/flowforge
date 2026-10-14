"use client";

import { Copy, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toaster";
import { useEditor } from "@/features/editor/editor-context";
import type { StepNode } from "@/features/editor/graph";
import { NodeIcon } from "@/features/editor/NodeIcon";
import { SchemaForm } from "@/features/editor/SchemaForm";
import type { Step, StepSettings } from "@/lib/types";

interface ConfigPanelProps {
  node: StepNode;
  webhookUrl: string;
  lastStep: Step | undefined;
  onChange: (patch: Partial<StepNode["data"]>, coalesceKey: string) => void;
  onDelete: () => void;
  onClose: () => void;
}

const SETTINGS_FIELDS: { key: keyof StepSettings; label: string; hint: string }[] = [
  { key: "retries", label: "Retries", hint: "0–5 extra attempts on temporary errors" },
  { key: "retry_delay_seconds", label: "Retry delay (s)", hint: "Doubles after each attempt" },
  { key: "timeout_seconds", label: "Timeout (s)", hint: "Per attempt, max 300" },
];

export function ConfigPanel({
  node,
  webhookUrl,
  lastStep,
  onChange,
  onDelete,
  onClose,
}: ConfigPanelProps) {
  const { types, issuesByNode, readOnly } = useEditor();
  const toast = useToast();
  const info = types.get(node.data.nodeType);
  const issues = issuesByNode.get(node.id) ?? [];
  const isTrigger = node.data.nodeType.startsWith("trigger_");

  const setConfig = (key: string, value: unknown) => {
    const config = { ...node.data.config };
    if (value === undefined) delete config[key];
    else config[key] = value;
    onChange({ config }, `config:${node.id}:${key}`);
  };
  const setSetting = (key: keyof StepSettings, value: number | boolean | undefined) => {
    const settings = { ...node.data.settings };
    if (value === undefined) delete settings[key];
    else (settings as Record<string, unknown>)[key] = value;
    onChange({ settings }, `settings:${node.id}:${key}`);
  };

  return (
    <aside
      className="absolute inset-y-0 right-0 z-20 flex h-full w-full max-w-96 shrink-0 flex-col border-l border-slate-200 bg-white shadow-xl md:static md:shadow-none"
      aria-label="Step settings"
    >
      <div className="flex items-start gap-3 border-b border-slate-100 px-4 py-3">
        <NodeIcon name={info?.icon ?? "box"} className="mt-1 size-5 text-slate-500" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-slate-900">{info?.label ?? node.data.nodeType}</p>
          <p className="text-xs text-slate-500">{info?.description}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close settings"
          className="rounded p-1 text-slate-400 hover:bg-slate-100"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        {issues.length > 0 && (
          <ul className="space-y-1 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {issues.map((issue) => (
              <li key={issue}>• {issue}</li>
            ))}
          </ul>
        )}

        <Field label="Name" htmlFor={`${node.id}-label`}>
          <Input
            id={`${node.id}-label`}
            disabled={readOnly}
            value={node.data.label}
            onChange={(e) => onChange({ label: e.target.value }, `label:${node.id}`)}
          />
        </Field>
        <p className="text-xs text-slate-500">
          Use the output of this step elsewhere with{" "}
          <code className="rounded bg-slate-100 px-1">{`{{ steps.${node.id}.output }}`}</code>
        </p>

        {node.data.nodeType === "trigger_webhook" && (
          <div className="space-y-2 rounded-md border border-slate-200 p-3 text-sm">
            <p className="font-medium text-slate-800">Webhook URL</p>
            <div className="flex gap-2">
              <code className="flex-1 truncate rounded bg-slate-100 px-2 py-1 text-xs">
                {webhookUrl}
              </code>
              <button
                type="button"
                aria-label="Copy webhook URL"
                onClick={() =>
                  void navigator.clipboard.writeText(webhookUrl).then(() => toast.success("Copied"))
                }
              >
                <Copy className="size-4 text-slate-500" />
              </button>
            </div>
            <p className="text-xs text-slate-500">
              POST JSON with header <code>X-FlowForge-Secret</code>. The secret is shown once when
              you first publish; rotate it from the toolbar menu.
            </p>
          </div>
        )}

        {info && (
          <SchemaForm
            nodeId={node.id}
            schema={info.config_schema}
            value={node.data.config}
            onChange={setConfig}
            disabled={readOnly}
          />
        )}

        {!isTrigger && (
          <details className="rounded-md border border-slate-200 px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">
              Error handling
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              {SETTINGS_FIELDS.map((field) => (
                <Field
                  key={field.key}
                  label={field.label}
                  htmlFor={`${node.id}-${field.key}`}
                  hint={field.hint}
                >
                  <Input
                    id={`${node.id}-${field.key}`}
                    type="number"
                    min={0}
                    disabled={readOnly}
                    value={(node.data.settings[field.key] as number | undefined) ?? ""}
                    onChange={(e) =>
                      setSetting(
                        field.key,
                        e.target.value === "" ? undefined : Number(e.target.value),
                      )
                    }
                  />
                </Field>
              ))}
              <label className="col-span-2 flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  disabled={readOnly}
                  checked={Boolean(node.data.settings.continue_on_error)}
                  onChange={(e) => setSetting("continue_on_error", e.target.checked || undefined)}
                />
                Continue the run if this step fails
              </label>
            </div>
          </details>
        )}

        {lastStep && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-slate-800">Last test run</p>
            {lastStep.error && (
              <p className="rounded bg-rose-50 px-2 py-1 text-xs text-rose-700">{lastStep.error}</p>
            )}
            <pre className="max-h-60 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
              {JSON.stringify(lastStep.output ?? null, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {!readOnly && (
        <div className="border-t border-slate-100 p-3">
          <Button variant="ghost" className="text-rose-600" onClick={onDelete}>
            <Trash2 className="size-4" aria-hidden /> Delete step
          </Button>
        </div>
      )}
    </aside>
  );
}
