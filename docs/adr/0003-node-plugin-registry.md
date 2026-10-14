# ADR-0003: Nodes are plugins in a registry, described by JSON Schema

- Status: Accepted

## Context

The product's value grows with the number of integrations. Adding a node must not require changes to the engine, the validator or the editor.

## Decision

Each node type is a subclass of `NodeType` with:

- `type`, `label`, `category`, `description`
- `config_schema`: a JSON Schema for its configuration
- `output_handles(config)`: the branches it can choose (static or derived from config, e.g. classification labels)
- `async execute(ctx) -> NodeResult`

All node types register in `app/engine/nodes/registry.py`. `GET /api/v1/node-types` returns the registry to the editor, which renders configuration forms from the schemas.

## Consequences

- Adding a node is one class plus tests (see `DEVELOPMENT.md`).
- The editor stays generic; a small form renderer supports the schema features we use (string, multiline, number, boolean, enum, string arrays, JSON, credential reference).
- Schema validation happens once on the server (on save and publish) and the same errors are shown in the editor.
