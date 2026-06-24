#!/usr/bin/env python3
"""Normalize Chinese manipulation-command synonyms to Day-1 surface forms.

The public maps retain the alias-to-semantic form used in the project report.
``normalize_instruction`` uses the same vocabulary to turn aliases into the
canonical Chinese terms expected by the rule parser.
"""

import re
from typing import Dict


COLOR_MAP = {
    "红色": "red",
    "红": "red",
    "蓝色": "blue",
    "蓝": "blue",
    "绿色": "green",
    "绿": "green",
}

TYPE_MAP = {
    "方块": "cube",
    "积木": "cube",
    "块": "cube",
    "圆柱": "cylinder",
    "盒子": "box",
    "容器": "box",
    "桌子": "table",
}

ACTION_MAP = {
    "拿起": "pick",
    "抓起": "pick",
    "取": "pick",
    "放到": "place",
    "放进": "place",
    "移动到": "pick_place",
    "挪到": "pick_place",
}

RELATION_MAP = {
    "里": "in",
    "里面": "in",
    "旁边": "near",
    "左边": "left_of",
    "右边": "right_of",
    "中央": "center",
}


_CANONICAL_COLOR = {"red": "红色", "blue": "蓝色", "green": "绿色"}
_CANONICAL_TYPE = {
    "cube": "方块",
    "cylinder": "圆柱",
    "box": "盒子",
    "table": "桌子",
}
# ``放进`` and ``放到`` share a high-level action label but encode different
# relation information.  Normalize action aliases at the surface level so that
# the parser can preserve this distinction.
_ACTION_SURFACE_MAP = {
    "拿起": "拿起",
    "抓起": "拿起",
    "取": "拿起",
    "放到": "放到",
    "放进": "放进",
    "移动到": "移动到",
    "挪到": "移动到",
}
_CANONICAL_RELATION = {
    "in": "里",
    "near": "旁边",
    "left_of": "左边",
    "right_of": "右边",
    "center": "中央",
}


def _replace_aliases(text: str, semantic_map: Dict[str, str], canonical_map: Dict[str, str]) -> str:
    """Replace every alias in one pass, preferring longer overlapping terms."""
    aliases = sorted(semantic_map, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(alias) for alias in aliases))
    return pattern.sub(lambda match: canonical_map[semantic_map[match.group(0)]], text)


def _replace_surface_aliases(text: str, replacements: Dict[str, str]) -> str:
    """Replace direct surface-form aliases while preserving syntax details."""
    aliases = sorted(replacements, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(alias) for alias in aliases))
    return pattern.sub(lambda match: replacements[match.group(0)], text)


def normalize_instruction(instruction: str) -> str:
    """Return a synonym-normalized Chinese instruction.

    This function changes only vocabulary aliases.  It deliberately does not
    decide whether an instruction is grammatical, refers to scene objects, or
    can be physically executed; those remain parser and validator duties.
    """
    if not isinstance(instruction, str):
        raise TypeError("Instruction must be a string.")

    normalized = _replace_aliases(instruction, COLOR_MAP, _CANONICAL_COLOR)
    normalized = _replace_aliases(normalized, TYPE_MAP, _CANONICAL_TYPE)
    normalized = _replace_surface_aliases(normalized, _ACTION_SURFACE_MAP)
    return _replace_aliases(normalized, RELATION_MAP, _CANONICAL_RELATION)
