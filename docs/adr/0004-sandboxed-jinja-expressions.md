# ADR-0004: Sandboxed Jinja2 for expressions

- Status: Accepted

## Context

Users must reference data from the trigger and earlier steps (`{{ steps.extract.output.email }}`) and do light formatting (`{{ trigger.body.name | upper }}`). Expressions are written by tenants and evaluated on our servers, so they must not be able to execute arbitrary code.

Options: Python `eval` (unsafe), JSONPath only (too limited), JavaScript in a sandbox (needs a JS runtime), Jinja2's sandbox.

## Decision

Use `jinja2.sandbox.ImmutableSandboxedEnvironment` with `StrictUndefined`:

- A string that is exactly one `{{ expression }}` is compiled as an expression and returns its native value.
- Any other string is rendered as a template and returns text.
- Rendering walks the whole `config` value recursively (lists and objects).

## Consequences

- Familiar syntax (also used by Ansible, dbt, Home Assistant) with filters out of the box.
- The sandbox blocks access to private attributes and mutation of objects; tests cover common escape attempts.
- Undefined names raise errors with the missing name, surfaced on the failing step.
- Expressions cannot call network or file APIs; that is intentional.
