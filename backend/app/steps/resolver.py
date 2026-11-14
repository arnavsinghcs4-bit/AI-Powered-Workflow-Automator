"""Template resolver for pipeline step inputs and transform mappings.

A template is ``{{path}}`` where ``path`` is a dotted key into the context
dict. Resolution rules:

* A string whose only content is a single ``{{path}}`` returns the raw
  context value -- no string coercion, so JSON types survive.
* A string containing one or more templates (or literal text) is
  interpolated: every ``{{path}}`` is replaced by ``str(value)``.
* ``{{...}}`` inside dicts and lists is resolved recursively.
* ``\\{{`` escapes to a literal ``{{``.

Decision 3 of the spec: transform mapping is ``{output_key: template}``
reusing this resolver.
"""

from __future__ import annotations

import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
ESCAPE_RE = re.compile(r"\\\{\{")
# Sentinel for an escaped ``\{{`` so it is never treated as a template.
_ESCAPED_SENTINEL = "\x00"


def _lookup(context: dict, path: str) -> Any:
    cur: Any = context
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(path)
        cur = cur[part]
    return cur


def resolve(value: Any, context: dict) -> Any:
    """Resolve ``{{...}}`` templates in ``value`` against ``context``."""
    if isinstance(value, str):
        # Replace escaped \{{ with a sentinel so the template regex never
        # sees them; restore the literal {{ after substitution.
        has_escape = ESCAPE_RE.search(value) is not None
        if has_escape:
            value = ESCAPE_RE.sub(_ESCAPED_SENTINEL, value)
        matches = _TEMPLATE_RE.findall(value)
        if not matches:
            return value if not has_escape else value.replace(_ESCAPED_SENTINEL, "{{")
        # Lone template: preserve the raw value's JSON type.
        if len(matches) == 1 and value.strip() == "{{" + matches[0] + "}}":
            result = _lookup(context, matches[0].strip())
            return result if not has_escape else result
        result = _TEMPLATE_RE.sub(
            lambda m: str(_lookup(context, m.group(1).strip())), value
        )
        return result if not has_escape else result.replace(_ESCAPED_SENTINEL, "{{")
    if isinstance(value, dict):
        return {k: resolve(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, context) for v in value]
    return value
