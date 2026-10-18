"""Thinking and effort sent explicitly on every request, per model.

The defaults and why: docs/investigacion-haiku.md, section 2.
"""

from typing import Any, Literal

Effort = Literal["low", "medium", "high", "xhigh", "max"]
Thinking = Literal["adaptive", "off"]

DEFAULT_EFFORT: dict[str, Effort] = {
    "claude-haiku-5-5": "medium",
    "claude-sonnet-5-5": "medium",
}
FALLBACK_EFFORT: Effort = "medium"
THINKING_OFF_LIMIT: tuple[Effort, ...] = ("low", "medium", "high")


def request_options(
    model: str, effort: Effort | None = None, thinking: Thinking = "adaptive"
) -> dict[str, Any]:
    """The `thinking` and `output_config` arguments for messages.create on this model."""
    level = effort or DEFAULT_EFFORT.get(model, FALLBACK_EFFORT)
    if thinking == "adaptive":
        config: dict[str, Any] = {"type": "adaptive"}
    elif level not in THINKING_OFF_LIMIT:
        raise ValueError(f"thinking off needs effort low, medium or high, not {level}")
    else:
        # Sonnet 5.5 rejects "disabled"; its lowest setting is "between_tools".
        config = {"type": "between_tools" if model == "claude-sonnet-5-5" else "disabled"}
    return {"thinking": config, "output_config": {"effort": level}}
