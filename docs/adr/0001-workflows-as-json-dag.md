# ADR-0001: Workflows are directed acyclic graphs stored as JSON

- Status: Accepted

## Context

Workflows must be edited visually, validated, versioned, diffed, exported and executed. Options: a relational model (tables for nodes and edges), a custom DSL (YAML), or a JSON document per workflow.

## Decision

Store each workflow graph as one JSON document in the format React Flow uses (`nodes` with `id`, `type`, `position`, `data`; `edges` with `source`, `target`, `sourceHandle`). Draft graphs live on `workflows.draft_graph`; published versions are immutable snapshots in `workflow_versions.graph`; every run stores the exact graph it executed.

Cycles are not allowed. Repetition is expressed with the `for_each` node, which runs another workflow per item.

## Consequences

- The editor saves exactly what it renders; no mapping layer.
- Versioning and export are copies of a document; diffs compare node and edge sets.
- Runs are reproducible even if the workflow changes while they are paused.
- Querying "which workflows use node X" needs JSONB queries instead of joins, which is acceptable at this scale.
- Forbidding cycles keeps the engine simple and guarantees termination; for-each covers the common iteration needs.
