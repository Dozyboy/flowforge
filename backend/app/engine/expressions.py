"""Sandboxed `{{ ... }}` expressions in node configuration (see docs/adr/0004)."""

import re
from functools import lru_cache
from typing import Any

from jinja2 import StrictUndefined, TemplateError, Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

_FULL_EXPRESSION = re.compile(r"^\s*\{\{(?P<expr>(?:(?!\}\}).)*)\}\}\s*$", re.DOTALL)
_HAS_TEMPLATE = re.compile(r"\{\{|\{%")
MAX_RENDERED_LENGTH = 200_000


class ExpressionError(ValueError):
    pass


class _Environment(ImmutableSandboxedEnvironment):
    """Prefer dictionary keys over attributes for `a.b`.

    Jinja normally tries attributes first, so `trigger.body.items` would return the dict's
    `items` method instead of an "items" field — a common surprise with JSON payloads.
    """

    def getattr(self, obj: Any, attribute: str) -> Any:
        if isinstance(obj, dict) and attribute in obj:
            return obj[attribute]
        return super().getattr(obj, attribute)


_env = _Environment(undefined=StrictUndefined, autoescape=False)


@lru_cache(maxsize=2048)
def _compile_expression(expression: str) -> Any:
    return _env.compile_expression(expression, undefined_to_none=False)


@lru_cache(maxsize=2048)
def _compile_template(source: str) -> Any:
    return _env.from_string(source)


def render_string(value: str, context: dict[str, Any]) -> Any:
    if not _HAS_TEMPLATE.search(value):
        return value
    try:
        full = _FULL_EXPRESSION.match(value)
        if full:
            result = _compile_expression(full.group("expr").strip())(**context)
            if isinstance(result, Undefined):
                raise ExpressionError(f"'{full.group('expr').strip()}' is not defined")
            return result
        rendered = _compile_template(value).render(**context)
    except ExpressionError:
        raise
    except Exception as exc:
        # TemplateError covers syntax, undefined names and sandbox violations; anything else
        # (e.g. TypeError from `1 + "a"`) is equally a mistake in the user's expression.
        kind = "Invalid expression" if isinstance(exc, TemplateError) else "Error in expression"
        raise ExpressionError(f"{kind} “{value[:120]}”: {exc}") from exc
    if len(rendered) > MAX_RENDERED_LENGTH:
        raise ExpressionError("Rendered text is too long")
    return rendered


def render_value(value: Any, context: dict[str, Any]) -> Any:
    """Render every string inside `value` (recursively through lists and objects)."""
    if isinstance(value, str):
        return render_string(value, context)
    if isinstance(value, list):
        return [render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, context) for key, item in value.items()}
    return value
