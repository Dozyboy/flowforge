# ADR-0005: No "run custom code" node

- Status: Accepted

## Context

Many automation tools offer a node that runs user-provided JavaScript or Python. It is powerful and frequently requested.

Running untrusted code from many tenants on shared workers is a serious security problem: Python cannot be sandboxed in-process, and escaping a container requires only one kernel or runtime bug. Doing it safely needs per-execution isolation (Firecracker microVMs, gVisor, WebAssembly with strict resource limits), separate infrastructure, and careful limits on CPU, memory, time and network.

## Decision

Do not provide a code node in v1. Cover the common needs with:

- `transform` (sandboxed expressions to reshape data),
- `condition` / `switch` for logic,
- `ai_extract` / `ai_generate` for fuzzy text processing,
- `http_request` to call the customer's own code (for example a serverless function).

## Consequences

- No tenant-supplied code runs on our workers.
- Some advanced transformations require an external function. If demand is strong, a code node can be added later on isolated runners (WebAssembly or microVMs) without changing the engine, thanks to the plugin registry.
