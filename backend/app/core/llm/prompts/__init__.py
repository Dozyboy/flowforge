"""Prompt templates live next to this module as `<name>.md` files.

Templates use `string.Template` placeholders (`$variable`) so that braces in JSON examples do not
need escaping. Bump the `_vN` suffix when changing a prompt's behavior, so evaluation reports can
be compared across versions.
"""

from functools import cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent


@cache
def _load(name: str) -> Template:
    return Template((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


def render_prompt(name: str, **variables: object) -> str:
    return _load(name).substitute({k: str(v) for k, v in variables.items()})
