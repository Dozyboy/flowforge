import pytest

from app.engine.expressions import ExpressionError, render_value

CONTEXT = {
    "trigger": {"body": {"name": "Ana", "amount": 1200, "items": [1, 2, 3]}},
    "steps": {"classify": {"output": {"label": "refund"}}},
}


def test_plain_strings_are_unchanged() -> None:
    assert render_value("hello", CONTEXT) == "hello"


def test_single_expression_returns_native_values() -> None:
    assert render_value("{{ trigger.body.amount }}", CONTEXT) == 1200
    assert render_value("{{ trigger.body.items }}", CONTEXT) == [1, 2, 3]
    assert render_value("  {{ trigger.body.amount > 1000 }} ", CONTEXT) is True


def test_mixed_text_is_rendered_as_string() -> None:
    assert render_value("Hi {{ trigger.body.name | upper }}!", CONTEXT) == "Hi ANA!"


def test_nested_structures_are_rendered() -> None:
    value = {"who": "{{ trigger.body.name }}", "tags": ["{{ steps.classify.output.label }}", 1]}
    assert render_value(value, CONTEXT) == {"who": "Ana", "tags": ["refund", 1]}


def test_undefined_names_fail_loudly() -> None:
    with pytest.raises(ExpressionError, match="not defined"):
        render_value("{{ trigger.body.missing }}", CONTEXT)
    with pytest.raises(ExpressionError):
        render_value("Hello {{ nobody.name }}", CONTEXT)


def test_syntax_errors_are_reported() -> None:
    with pytest.raises(ExpressionError, match="Invalid expression"):
        render_value("{{ trigger.body. }}", CONTEXT)


@pytest.mark.parametrize(
    "attack",
    [
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{ trigger.__class__ }}",
        "{{ trigger.body.items.append(4) }}",
        "{{ cycler.__init__.__globals__ }}",
    ],
)
def test_sandbox_blocks_escapes_and_mutation(attack: str) -> None:
    with pytest.raises(ExpressionError):
        render_value(attack, CONTEXT)
