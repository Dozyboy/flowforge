"""Workflow graph model and validation (see docs/adr/0001-workflows-as-json-dag.md)."""

import re
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.config import get_settings

if TYPE_CHECKING:
    from app.engine.nodes.registry import NodeRegistry

NODE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_NODES = 200


class GraphError(ValueError):
    """The graph JSON is structurally broken (not just invalid for publishing)."""


@dataclass(frozen=True)
class StepSettings:
    retries: int = 0
    retry_delay_seconds: float = 2.0
    timeout_seconds: float = 30.0
    continue_on_error: bool = False

    @classmethod
    def parse(cls, raw: Any) -> "StepSettings":
        settings = get_settings()
        data = raw if isinstance(raw, dict) else {}

        def number(key: str, default: float, low: float, high: float) -> float:
            try:
                return min(high, max(low, float(data.get(key, default))))
            except (TypeError, ValueError):
                return default

        return cls(
            retries=int(number("retries", 0, 0, 5)),
            retry_delay_seconds=number("retry_delay_seconds", 2.0, 0, 300),
            timeout_seconds=number(
                "timeout_seconds",
                settings.default_step_timeout_seconds,
                1,
                settings.max_step_timeout_seconds,
            ),
            continue_on_error=bool(data.get("continue_on_error", False)),
        )


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    label: str
    config: dict[str, Any]
    settings: StepSettings


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    source_handle: str | None


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[Edge]
    _incoming: dict[str, list[Edge]] = field(default_factory=dict, repr=False)
    _outgoing: dict[str, list[Edge]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for node_id in self.nodes:
            self._incoming[node_id] = []
            self._outgoing[node_id] = []
        for edge in self.edges:
            if edge.source in self.nodes and edge.target in self.nodes:
                self._outgoing[edge.source].append(edge)
                self._incoming[edge.target].append(edge)

    @classmethod
    def parse(cls, data: Any) -> "Graph":
        if not isinstance(data, dict):
            raise GraphError("Graph must be an object with 'nodes' and 'edges'")
        raw_nodes, raw_edges = data.get("nodes", []), data.get("edges", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise GraphError("'nodes' and 'edges' must be lists")
        if len(raw_nodes) > MAX_NODES:
            raise GraphError(f"A workflow can have at most {MAX_NODES} nodes")

        nodes: dict[str, Node] = {}
        for raw in raw_nodes:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                raise GraphError("Every node needs a string 'id'")
            raw_data = raw.get("data")
            node_data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
            config = node_data.get("config", {})
            node = Node(
                id=raw["id"],
                type=str(raw.get("type", "")),
                label=str(node_data.get("label") or raw["id"]),
                config=config if isinstance(config, dict) else {},
                settings=StepSettings.parse(node_data.get("settings")),
            )
            if node.id in nodes:
                raise GraphError(f"Duplicate node id '{node.id}'")
            nodes[node.id] = node

        edges: list[Edge] = []
        for index, raw in enumerate(raw_edges):
            if not isinstance(raw, dict):
                raise GraphError("Every edge must be an object")
            handle = raw.get("sourceHandle")
            edges.append(
                Edge(
                    id=str(raw.get("id") or f"e{index}"),
                    source=str(raw.get("source", "")),
                    target=str(raw.get("target", "")),
                    source_handle=str(handle) if handle not in (None, "") else None,
                )
            )
        return cls(nodes=nodes, edges=edges)

    def incoming(self, node_id: str) -> list[Edge]:
        return self._incoming.get(node_id, [])

    def outgoing(self, node_id: str) -> list[Edge]:
        return self._outgoing.get(node_id, [])

    def triggers(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.type.startswith("trigger_")]

    def trigger(self) -> Node:
        triggers = self.triggers()
        if len(triggers) != 1:
            raise GraphError("A workflow needs exactly one trigger")
        return triggers[0]

    def terminal_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if not self.outgoing(n.id)]

    def topological_order(self) -> list[str]:
        """Kahn's algorithm. Nodes that are part of a cycle are left out."""
        in_degree = {node_id: len(self.incoming(node_id)) for node_id in self.nodes}
        queue = deque(sorted(n for n, d in in_degree.items() if d == 0))
        order: list[str] = []
        while queue:
            node_id = queue.popleft()
            order.append(node_id)
            for edge in self.outgoing(node_id):
                in_degree[edge.target] -= 1
                if in_degree[edge.target] == 0:
                    queue.append(edge.target)
        return order


@dataclass(frozen=True)
class GraphIssue:
    node_id: str | None
    message: str

    def as_dict(self) -> dict[str, str | None]:
        return {"node_id": self.node_id, "message": self.message}


def validate_graph(data: Any, registry: "NodeRegistry") -> list[GraphIssue]:
    """All problems that prevent publishing. An empty list means the graph can run."""
    try:
        graph = Graph.parse(data)
    except GraphError as exc:
        return [GraphIssue(None, str(exc))]

    issues: list[GraphIssue] = []
    if not graph.nodes:
        return [GraphIssue(None, "Add a trigger to start the workflow")]

    triggers = graph.triggers()
    if not triggers:
        issues.append(GraphIssue(None, "The workflow needs a trigger"))
    elif len(triggers) > 1:
        issues.extend(GraphIssue(t.id, "Only one trigger is allowed") for t in triggers[1:])

    for node in graph.nodes.values():
        if not NODE_ID_RE.match(node.id):
            issues.append(
                GraphIssue(node.id, "Node ids may only contain letters, digits and underscores")
            )
        node_type = registry.get(node.type)
        if node_type is None:
            issues.append(GraphIssue(node.id, f"Unknown node type '{node.type}'"))
            continue
        issues.extend(
            GraphIssue(node.id, problem) for problem in node_type.validate_config(node.config)
        )
        if node.type.startswith("trigger_") and graph.incoming(node.id):
            issues.append(GraphIssue(node.id, "A trigger cannot have incoming connections"))
        if not node.type.startswith("trigger_") and not graph.incoming(node.id):
            issues.append(GraphIssue(node.id, "This step is not connected to the workflow"))

    for edge in graph.edges:
        if edge.source not in graph.nodes or edge.target not in graph.nodes:
            issues.append(GraphIssue(None, f"Connection '{edge.id}' points to a missing step"))
            continue
        if edge.source == edge.target:
            issues.append(GraphIssue(edge.source, "A step cannot connect to itself"))
        source = graph.nodes[edge.source]
        source_type = registry.get(source.type)
        if source_type is None:
            continue
        handles = source_type.output_handles(source.config)
        if handles and edge.source_handle not in handles:
            issues.append(
                GraphIssue(
                    source.id,
                    f"Connections from this step must use one of its outputs: {', '.join(handles)}",
                )
            )
        if not handles and edge.source_handle is not None:
            issues.append(GraphIssue(source.id, "This step has a single output"))

    ordered = set(graph.topological_order())
    cyclic = sorted(set(graph.nodes) - ordered)
    if cyclic:
        issues.append(
            GraphIssue(cyclic[0], f"The workflow contains a loop through: {', '.join(cyclic)}")
        )
    return issues
