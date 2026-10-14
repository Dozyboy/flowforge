from typing import Any

from app.engine.graph import Graph, StepSettings, validate_graph
from app.engine.nodes.registry import registry
from tests.graphs import edge, graph, node


def _messages(data: dict[str, Any]) -> list[str]:
    return [issue.message for issue in validate_graph(data, registry)]


def test_valid_linear_graph_has_no_issues() -> None:
    data = graph(
        [node("start", "trigger_manual"), node("log1", "log", {"message": "hi"})],
        [edge("start", "log1")],
    )
    assert validate_graph(data, registry) == []


def test_requires_exactly_one_trigger() -> None:
    assert "The workflow needs a trigger" in _messages(
        graph([node("a", "log", {"message": "x"})], [])
    )
    two = graph([node("a", "trigger_manual"), node("b", "trigger_webhook")], [])
    assert "Only one trigger is allowed" in _messages(two)


def test_detects_cycles() -> None:
    data = graph(
        [
            node("start", "trigger_manual"),
            node("a", "log", {"message": "a"}),
            node("b", "log", {"message": "b"}),
        ],
        [edge("start", "a"), edge("a", "b"), edge("b", "a")],
    )
    assert any("loop" in m for m in _messages(data))


def test_branch_handles_must_match_node_outputs() -> None:
    data = graph(
        [
            node("start", "trigger_manual"),
            node("check", "condition", {"left": "1", "operator": "equals", "right": "1"}),
            node("a", "log", {"message": "a"}),
        ],
        [edge("start", "check"), edge("check", "a", "maybe")],
    )
    assert any("true, false" in m for m in _messages(data))


def test_classify_handles_come_from_labels() -> None:
    classify = registry.get("ai_classify")
    assert classify is not None
    assert classify.output_handles({"text": "x", "labels": ["refund", "bug"]}) == ["refund", "bug"]
    switch = registry.get("switch")
    assert switch is not None
    assert switch.output_handles({"value": "x", "cases": ["a"]}) == ["a", "default"]


def test_config_schema_and_unknown_types_are_reported() -> None:
    data = graph(
        [node("start", "trigger_manual"), node("s", "ai_summarize", {}), node("x", "nope")],
        [edge("start", "s"), edge("s", "x")],
    )
    messages = _messages(data)
    assert "'text' is a required property" in messages
    assert "Unknown node type 'nope'" in messages


def test_disconnected_steps_and_bad_ids() -> None:
    data = graph(
        [node("start", "trigger_manual"), node("bad-id", "log", {"message": "x"})],
        [],
    )
    messages = _messages(data)
    assert "This step is not connected to the workflow" in messages
    assert "Node ids may only contain letters, digits and underscores" in messages


def test_schedule_trigger_validates_cron_and_timezone() -> None:
    bad = graph(
        [node("start", "trigger_schedule", {"cron": "every day", "timezone": "Mars/Base"})], []
    )
    messages = _messages(bad)
    assert "cron: not a valid cron expression" in messages
    assert "timezone: unknown time zone 'Mars/Base'" in messages


def test_step_settings_are_clamped() -> None:
    settings = StepSettings.parse(
        {"retries": 99, "timeout_seconds": 10_000, "retry_delay_seconds": -5}
    )
    assert settings.retries == 5
    assert settings.timeout_seconds == 300
    assert settings.retry_delay_seconds == 0


def test_terminal_nodes_and_topological_order() -> None:
    parsed = Graph.parse(
        graph(
            [node("t", "trigger_manual"), node("a", "log"), node("b", "log"), node("c", "log")],
            [edge("t", "a"), edge("t", "b"), edge("a", "c"), edge("b", "c")],
        )
    )
    order = parsed.topological_order()
    assert order.index("t") < order.index("a") < order.index("c")
    assert [n.id for n in parsed.terminal_nodes()] == ["c"]
