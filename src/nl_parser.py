#!/usr/bin/env python3
"""Parse normalized Chinese manipulation instructions into the task DSL."""

import argparse
import json
import re
from typing import Any, Dict, Optional

from synonym_normalizer import normalize_instruction


class ParseError(ValueError):
    """Raised when an instruction does not match a supported rule template."""


COLOR_MAP = {
    "红色": "red",
    "蓝色": "blue",
    "绿色": "green",
}

TYPE_MAP = {
    "方块": "cube",
    "圆柱": "cylinder",
    "盒子": "box",
    "桌子": "table",
}

OBJECT_PATTERN = "(?:红色|蓝色|绿色)?(?:方块|圆柱|盒子|桌子)"
PLACEMENT_PATTERN = re.compile(
    rf"^(?:请)?(?:把|将)?(?P<target>{OBJECT_PATTERN})"
    rf"(?P<verb>放进|放到|移动到)(?P<destination>{OBJECT_PATTERN})"
    rf"(?P<suffix>里|里面|旁边|左边|右边|中央)?$"
)
PICK_PREFIX_PATTERN = re.compile(
    rf"^(?:请)?(?:拿起|抓起|取)(?P<target>{OBJECT_PATTERN})$"
)
PICK_SUFFIX_PATTERN = re.compile(
    rf"^(?:请)?(?:把|将)(?P<target>{OBJECT_PATTERN})(?:拿起|抓起|取)$"
)


def _clean_instruction(instruction: str) -> str:
    """Remove harmless whitespace and sentence-final punctuation."""
    if not isinstance(instruction, str):
        raise ParseError("Instruction must be a string.")

    cleaned = re.sub(r"\s+", "", instruction)
    cleaned = cleaned.rstrip("。！？!?；;")
    if not cleaned:
        raise ParseError("Instruction is empty.")
    return cleaned


def _parse_object(expression: str) -> Dict[str, Optional[str]]:
    """Convert a canonical Day-1 Chinese object phrase to an object reference."""
    color = next((word for word in COLOR_MAP if expression.startswith(word)), None)
    type_word = expression[len(color) :] if color else expression
    object_type = TYPE_MAP.get(type_word)
    if object_type is None:
        raise ParseError(f"Unsupported object expression: {expression}")
    return {
        "type": object_type,
        "color": COLOR_MAP[color] if color else None,
    }


def _relation_for(verb: str, suffix: Optional[str]) -> str:
    """Infer the final spatial relation from the placement template."""
    if verb == "放进":
        if suffix in (None, "里", "里面"):
            return "in"
        raise ParseError("'放进' can only be followed by '里' or '里面'.")

    suffix_relations = {
        "里": "in",
        "里面": "in",
        "旁边": "near",
        "左边": "left_of",
        "右边": "right_of",
        "中央": "center",
    }
    relation = suffix_relations.get(suffix)
    if relation is None:
        raise ParseError("Missing spatial relation after '放到' or '移动到'.")
    return relation


def parse_instruction(instruction: str) -> Dict[str, Any]:
    """Return a canonical DSL dictionary for one supported Chinese command.

    Supported Day-1 examples include ``拿起红色方块`` and the placement forms
    ``放进``, ``放到...中央``, and ``移动到...旁边``.  This function performs
    syntactic parsing only; object existence and action feasibility are checked
    later by grounding and validation.
    """
    normalized = normalize_instruction(_clean_instruction(instruction))

    for pick_pattern in (PICK_PREFIX_PATTERN, PICK_SUFFIX_PATTERN):
        match = pick_pattern.fullmatch(normalized)
        if match:
            return {
                "intent": "pick",
                "target": _parse_object(match.group("target")),
            }

    match = PLACEMENT_PATTERN.fullmatch(normalized)
    if not match:
        raise ParseError(f"Unsupported instruction: {instruction}")

    return {
        "intent": "pick_place",
        "target": _parse_object(match.group("target")),
        "destination": _parse_object(match.group("destination")),
        "relation": _relation_for(match.group("verb"), match.group("suffix")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a Chinese manipulation instruction into DSL.")
    parser.add_argument("instruction", help="For example: 把红色方块放进蓝色盒子里")
    args = parser.parse_args()

    try:
        dsl = parse_instruction(args.instruction)
    except ParseError as error:
        parser.exit(2, f"Parse error: {error}\n")
    print(json.dumps(dsl, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
