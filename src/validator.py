#!/usr/bin/env python3
"""Scene-aware validation for parsed Chinese manipulation instructions."""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from nl_parser import ParseError, parse_instruction
from synonym_normalizer import normalize_instruction


@dataclass(frozen=True)
class ValidationResult:
    """The stable outcome returned by the validator API and CLI."""

    valid: bool
    reason: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"valid": self.valid}
        if self.reason is not None:
            result["reason"] = self.reason
        return result


class TaskValidator:
    """Validate task DSLs against a static scene object table.

    ``in`` and ``on`` require an explicit destination capability in
    ``objects.json``. Positional relations such as ``near`` and ``left_of``
    use a unique scene object only as a reference point, so they do not need an
    ``accepts`` entry.
    """

    CONTAINER_RELATIONS = {"in", "on"}
    POSITIONAL_RELATIONS = {"near", "left_of", "right_of", "center"}

    def __init__(self, objects_path: str | Path):
        path = Path(objects_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Object table not found: {path}")
        with path.open(encoding="utf-8") as object_file:
            scene = json.load(object_file)
        objects = scene.get("objects")
        if not isinstance(objects, list):
            raise ValueError("Object table must contain an 'objects' list.")
        self.objects: List[Dict[str, Any]] = objects

    @staticmethod
    def _matches(reference: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
        object_id = reference.get("id")
        object_type = reference.get("type")
        color = reference.get("color")
        if object_id is not None and candidate.get("id") != object_id:
            return False
        if object_type is not None and candidate.get("type") != object_type:
            return False
        if color is not None and candidate.get("color") != color:
            return False
        return True

    def _matching_objects(self, reference: Dict[str, Any], *, role: str) -> List[Dict[str, Any]]:
        matches = [candidate for candidate in self.objects if self._matches(reference, candidate)]
        if role == "target":
            matches = [candidate for candidate in matches if candidate.get("pickable", False)]
        return matches

    @staticmethod
    def _reference_error(reference: Any, role: str) -> Optional[ValidationResult]:
        if not isinstance(reference, dict) or not reference:
            return ValidationResult(False, f"missing {role}")
        if reference.get("id") is None and reference.get("type") is None:
            return ValidationResult(False, f"missing {role}")
        return None

    def _resolve(self, reference: Dict[str, Any], *, role: str) -> tuple[Optional[Dict[str, Any]], Optional[ValidationResult]]:
        matches = self._matching_objects(reference, role=role)
        if not matches:
            return None, ValidationResult(False, f"{role} not found")
        if len(matches) > 1:
            return None, ValidationResult(False, f"ambiguous {role}")
        return matches[0], None

    def validate(self, task: Dict[str, Any]) -> ValidationResult:
        """Check DSL structure, object references, and relation feasibility."""
        if not isinstance(task, dict):
            return ValidationResult(False, "invalid task DSL")

        intent = task.get("intent")
        if intent not in {"pick", "pick_place"}:
            return ValidationResult(False, "unsupported intent")

        target_reference = task.get("target")
        reference_error = self._reference_error(target_reference, "target")
        if reference_error:
            return reference_error
        target, target_error = self._resolve(target_reference, role="target")
        if target_error:
            return target_error

        if intent == "pick":
            return ValidationResult(True)

        destination_reference = task.get("destination")
        reference_error = self._reference_error(destination_reference, "destination")
        if reference_error:
            return reference_error
        relation = task.get("relation")
        if relation not in self.CONTAINER_RELATIONS | self.POSITIONAL_RELATIONS:
            return ValidationResult(False, "unsupported relation")

        destination, destination_error = self._resolve(destination_reference, role="destination")
        if destination_error:
            return destination_error
        if target["id"] == destination["id"]:
            return ValidationResult(False, "same target and destination")

        if relation in self.CONTAINER_RELATIONS and relation not in destination.get("accepts", []):
            return ValidationResult(False, "destination does not support relation")
        return ValidationResult(True)


def _compact_instruction(instruction: str) -> str:
    return re.sub(r"\s+", "", instruction).rstrip("。！？!?；;")


def _parse_error_reason(instruction: str) -> str:
    """Classify parse failures needed by the Day-3 invalid-command set."""
    normalized = normalize_instruction(_compact_instruction(instruction))
    if any(word in normalized for word in ("上面", "下面", "前面", "后面")):
        return "unsupported relation"
    if re.fullmatch(
        r"(?:请)?(?:把|将)?(?:红色|蓝色|绿色)?(?:方块|圆柱|盒子|桌子)"
        r"(?:放进|放到|移动到)(?:里|里面|旁边|左边|右边|中央)",
        normalized,
    ):
        return "missing destination"
    if re.match(r"^(?:请)?(?:放进|放到|移动到)", normalized):
        return "missing target"
    if any(word in normalized for word in ("随便", "一个", "东西", "它")):
        return "ambiguous target"
    return "unsupported instruction"


def validate_instruction(instruction: str, validator: TaskValidator) -> ValidationResult:
    """Parse one instruction and return its scene-aware validation result."""
    try:
        task = parse_instruction(instruction)
    except ParseError:
        return ValidationResult(False, _parse_error_reason(instruction))
    return validator.validate(task)


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Validate a Chinese manipulation instruction.")
    parser.add_argument("instruction", help="For example: 把红色方块放进蓝色盒子里")
    parser.add_argument("--objects", default=root / "configs" / "objects.json")
    args = parser.parse_args()

    result = validate_instruction(args.instruction, TaskValidator(args.objects))
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
