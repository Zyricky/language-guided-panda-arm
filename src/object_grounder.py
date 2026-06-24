#!/usr/bin/env python3
"""Resolve task-DSL object descriptions against ``configs/objects.json``."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class GroundingError(ValueError):
    """Raised when a referring expression cannot identify one object."""


@dataclass(frozen=True)
class GroundedObject:
    object_id: str
    object_type: str
    color: Optional[str]
    position: List[float]
    raw: Dict[str, Any]

    @property
    def expression(self) -> str:
        return " ".join(part for part in (self.color, self.object_type) if part)


class ObjectGrounder:
    """Ground object references using the static scene object table.

    A target must be pickable. A destination must declare that it accepts the
    requested spatial relation, for example ``blue box`` accepts ``in``.
    """

    def __init__(self, objects_path: str):
        path = Path(objects_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Object table not found: {path}")

        with path.open(encoding="utf-8") as file:
            scene = json.load(file)

        objects = scene.get("objects")
        if not isinstance(objects, list):
            raise GroundingError("Object table must contain an 'objects' list.")
        self.objects = objects

    @staticmethod
    def format_expression(reference: Dict[str, Any]) -> str:
        return " ".join(
            str(part)
            for part in (reference.get("color"), reference.get("type"))
            if part is not None
        )

    @staticmethod
    def _grounded_object(candidate: Dict[str, Any]) -> GroundedObject:
        try:
            position = candidate["pose"]["position"]
            return GroundedObject(
                object_id=candidate["id"],
                object_type=candidate["type"],
                color=candidate.get("color"),
                position=position,
                raw=candidate,
            )
        except (KeyError, TypeError) as error:
            raise GroundingError(f"Malformed object entry: {candidate!r}") from error

    def ground(
        self,
        reference: Dict[str, Any],
        *,
        role: str,
        relation: Optional[str] = None,
    ) -> GroundedObject:
        """Return exactly one object matching an object reference.

        ``role`` is either ``target`` or ``destination``. For a destination,
        ``relation`` is matched against its ``accepts`` list.
        """
        if role not in {"target", "destination"}:
            raise ValueError("role must be 'target' or 'destination'.")
        if not isinstance(reference, dict):
            raise GroundingError("Object reference must be a JSON object.")

        object_id = reference.get("id")
        object_type = reference.get("type")
        color = reference.get("color")
        if object_id is None and object_type is None:
            raise GroundingError("Object reference needs at least 'id' or 'type'.")

        candidates = []
        for candidate in self.objects:
            if object_id is not None and candidate.get("id") != object_id:
                continue
            if object_type is not None and candidate.get("type") != object_type:
                continue
            if color is not None and candidate.get("color") != color:
                continue
            if role == "target" and not candidate.get("pickable", False):
                continue
            if role == "destination":
                if relation is None:
                    raise GroundingError("Destination grounding requires a relation.")
                if relation not in candidate.get("accepts", []):
                    continue
            candidates.append(candidate)

        expression = self.format_expression(reference) or str(object_id)
        if not candidates:
            relation_hint = f" that accepts relation '{relation}'" if relation else ""
            raise GroundingError(f"No {role} matches '{expression}'{relation_hint}.")
        if len(candidates) > 1:
            ids = ", ".join(candidate["id"] for candidate in candidates)
            raise GroundingError(
                f"Ambiguous {role} '{expression}': matched {ids}. Add an exact id."
            )
        return self._grounded_object(candidates[0])

    def ground_task(self, task: Dict[str, Any]) -> Dict[str, GroundedObject]:
        """Ground the target and destination fields of a ``pick_place`` DSL."""
        if task.get("intent") != "pick_place":
            raise GroundingError("Only the 'pick_place' intent is supported.")
        relation = task.get("relation")
        if relation not in {"in", "on"}:
            raise GroundingError("Task relation must be 'in' or 'on'.")
        return {
            "target": self.ground(task.get("target"), role="target"),
            "destination": self.ground(
                task.get("destination"), role="destination", relation=relation
            ),
        }


def print_grounding(label: str, reference: Dict[str, Any], grounded: GroundedObject) -> None:
    """Print the Day-4 demo log in a stable, easy-to-read format."""
    expression = ObjectGrounder.format_expression(reference) or grounded.object_id
    pose = ", ".join(f"{value:.2f}" for value in grounded.position)
    print(f"Instruction {label}: {expression}")
    print(f"Grounded {label}: {grounded.object_id}")
    print(f"Grounded pose: [{pose}]")


def _parse_expression(expression: str) -> Dict[str, Any]:
    words = expression.lower().split()
    if len(words) == 1:
        return {"type": words[0], "color": None}
    if len(words) == 2:
        return {"color": words[0], "type": words[1]}
    raise GroundingError("Use a simple expression such as 'red cube' or 'table'.")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Ground a task DSL against the object table.")
    parser.add_argument("--objects", default=root / "configs" / "objects.json")
    parser.add_argument("--target", help="Demo target expression, e.g. 'red cube'.")
    parser.add_argument("--task-file", help="JSON file containing a full task DSL.")
    args = parser.parse_args()

    if args.target and args.task_file:
        parser.error("Use either --target or --task-file, not both.")

    grounder = ObjectGrounder(args.objects)
    if args.target:
        reference = _parse_expression(args.target)
        grounded = grounder.ground(reference, role="target")
        print_grounding("target", reference, grounded)
        return

    if args.task_file:
        with Path(args.task_file).expanduser().open(encoding="utf-8") as file:
            task = json.load(file)
    else:
        task = {
            "intent": "pick_place",
            "target": {"type": "cube", "color": "red"},
            "destination": {"type": "box", "color": "blue"},
            "relation": "in",
        }
    grounded = grounder.ground_task(task)
    print_grounding("target", task["target"], grounded["target"])
    print_grounding("destination", task["destination"], grounded["destination"])


if __name__ == "__main__":
    main()
