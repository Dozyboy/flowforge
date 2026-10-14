"use client";

import Link from "next/link";
import { useState, type KeyboardEvent } from "react";

import { Field, Input, Select, Textarea } from "@/components/ui/Field";
import { useEditor } from "@/features/editor/editor-context";
import { useWorkspace } from "@/features/workspace/workspace-context";
import type { JsonSchema } from "@/lib/types";

interface FieldProps {
  name: string;
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  fieldId: string;
}

function TagsInput({ value, onChange, disabled, fieldId }: FieldProps) {
  const items = Array.isArray(value) ? value.map(String) : [];
  const [draft, setDraft] = useState("");
  const add = () => {
    const next = draft.trim();
    if (next && !items.includes(next)) onChange([...items, next]);
    setDraft("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add();
    } else if (event.key === "Backspace" && !draft && items.length) {
      onChange(items.slice(0, -1));
    }
  };
  return (
    <div className="rounded-md border border-slate-300 bg-white p-1.5">
      <div className="flex flex-wrap gap-1">
        {items.map((item) => (
          <span
            key={item}
            className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700"
          >
            {item}
            {!disabled && (
              <button
                type="button"
                aria-label={`Remove ${item}`}
                onClick={() => onChange(items.filter((i) => i !== item))}
                className="text-slate-400 hover:text-slate-700"
              >
                ×
              </button>
            )}
          </span>
        ))}
        <input
          id={fieldId}
          disabled={disabled}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={add}
          placeholder={items.length ? "" : "Type and press Enter"}
          className="min-w-24 flex-1 border-0 p-1 text-sm focus:outline-none"
        />
      </div>
    </div>
  );
}

function JsonInput({ value, onChange, disabled, fieldId }: FieldProps) {
  const [text, setText] = useState(() =>
    value === undefined ? "" : JSON.stringify(value, null, 2),
  );
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Textarea
        id={fieldId}
        rows={6}
        disabled={disabled}
        className="font-mono text-xs"
        value={text}
        aria-invalid={error ? true : undefined}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) {
            setError(null);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(e.target.value));
            setError(null);
          } catch {
            setError("Not valid JSON yet");
          }
        }}
      />
      {error && <p className="text-xs text-amber-600">{error}</p>}
    </>
  );
}

function CredentialSelect({ schema, value, onChange, disabled, fieldId }: FieldProps) {
  const { credentials } = useEditor();
  const { basePath } = useWorkspace();
  const allowed = schema["x-credential-types"] ?? [];
  const options = credentials.filter((c) => allowed.length === 0 || allowed.includes(c.type));
  return (
    <>
      <Select
        id={fieldId}
        disabled={disabled}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        <option value="">— Choose a credential —</option>
        {options.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </Select>
      {options.length === 0 && (
        <p className="text-xs text-slate-500">
          No matching credentials.{" "}
          <Link href={`${basePath}/credentials`} className="text-indigo-600" target="_blank">
            Add one
          </Link>
        </p>
      )}
    </>
  );
}

function WorkflowSelect({ value, onChange, disabled, fieldId }: FieldProps) {
  const { workflows, currentWorkflowId } = useEditor();
  const options = workflows.filter((w) => w.id !== currentWorkflowId);
  return (
    <Select
      id={fieldId}
      disabled={disabled}
      value={typeof value === "string" ? value : ""}
      onChange={(e) => onChange(e.target.value || undefined)}
    >
      <option value="">— Choose a workflow —</option>
      {options.map((w) => (
        <option key={w.id} value={w.id} disabled={w.published_version === null}>
          {w.name}
          {w.published_version === null ? " (not published)" : ""}
        </option>
      ))}
    </Select>
  );
}

function SchemaField(props: FieldProps) {
  const { schema, value, onChange, disabled, fieldId } = props;
  const ui = schema["x-ui"];
  if (ui === "tags") return <TagsInput {...props} />;
  if (ui === "json") return <JsonInput {...props} />;
  if (ui === "credential") return <CredentialSelect {...props} />;
  if (ui === "workflow") return <WorkflowSelect {...props} />;
  if (schema.enum) {
    return (
      <Select
        id={fieldId}
        disabled={disabled}
        value={String(value ?? schema.default ?? "")}
        onChange={(e) => onChange(e.target.value)}
      >
        {schema.enum.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option).replaceAll("_", " ")}
          </option>
        ))}
      </Select>
    );
  }
  if (schema.type === "boolean") {
    return (
      <input
        id={fieldId}
        type="checkbox"
        disabled={disabled}
        checked={Boolean(value ?? schema.default)}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 rounded border-slate-300"
      />
    );
  }
  if (schema.type === "integer" || schema.type === "number") {
    return (
      <Input
        id={fieldId}
        type="number"
        disabled={disabled}
        min={schema.minimum}
        max={schema.maximum}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  }
  if (ui === "textarea") {
    return (
      <Textarea
        id={fieldId}
        rows={4}
        disabled={disabled}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <Input
      id={fieldId}
      disabled={disabled}
      value={typeof value === "string" ? value : value === undefined ? "" : String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

interface SchemaFormProps {
  nodeId: string;
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled: boolean;
}

/** Renders a configuration form from a node type's JSON Schema. */
export function SchemaForm({ nodeId, schema, value, onChange, disabled }: SchemaFormProps) {
  const required = new Set(schema.required ?? []);
  const properties = Object.entries(schema.properties ?? {});
  if (properties.length === 0) {
    return <p className="text-sm text-slate-500">This step has no settings.</p>;
  }
  return (
    <div className="space-y-4">
      {properties.map(([key, fieldSchema]) => {
        const fieldId = `${nodeId}-${key}`;
        return (
          <Field
            key={`${nodeId}-${key}`}
            label={`${fieldSchema.title ?? key}${required.has(key) ? " *" : ""}`}
            htmlFor={fieldId}
            hint={fieldSchema.description}
          >
            <SchemaField
              name={key}
              schema={fieldSchema}
              value={value[key]}
              onChange={(next) => onChange(key, next)}
              disabled={disabled}
              fieldId={fieldId}
            />
          </Field>
        );
      })}
    </div>
  );
}
