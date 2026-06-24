#!/usr/bin/env python3
"""Run one Chinese manipulation instruction through the Panda arm pipeline.

This entry point intentionally supports the executable subset of the current
robot stack: one ``pick_place`` instruction with an ``in`` or ``on`` relation.
Natural-language forms outside that subset are parsed and validated elsewhere,
but are stopped here before they can reach motion execution.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from arm_executor import ArmExecutor
from nl_parser import ParseError, parse_instruction
from object_grounder import GroundedObject, GroundingError, ObjectGrounder, print_grounding
from skill_planner import PlanningError, Skill, SkillPlanner
from validator import TaskValidator


class NLTaskError(RuntimeError):
    """Raised when an NL command cannot safely enter the execution pipeline."""

    def __init__(self, stage: str, reason: str):
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class PreparedNLTask:
    """A parsed, validated, grounded, and planned executable instruction."""

    instruction: str
    task: Dict[str, Any]
    grounded: Dict[str, GroundedObject]
    plan: List[Skill]


def prepare_nl_task(instruction: str, objects_path: str | Path) -> PreparedNLTask:
    """Turn one instruction into a safe, executable symbolic task.

    Parsing and semantic validation happen before object grounding.  The final
    scope guard prevents valid but not-yet-implemented relations such as
    ``near`` from reaching the existing pick-and-place executor.
    """
    try:
        task = parse_instruction(instruction)
    except ParseError as error:
        raise NLTaskError("Parse error", str(error)) from error

    validator = TaskValidator(objects_path)
    validation = validator.validate(task)
    if not validation.valid:
        raise NLTaskError("Validation failed", validation.reason or "invalid instruction")

    if task.get("intent") != "pick_place" or task.get("relation") not in {"in", "on"}:
        raise NLTaskError(
            "Execution not supported",
            "current arm executor supports only pick_place instructions with relation in/on",
        )

    try:
        grounded = ObjectGrounder(str(objects_path)).ground_task(task)
        plan = SkillPlanner().plan(task, grounded)
    except (GroundingError, PlanningError) as error:
        raise NLTaskError("Planning failed", str(error)) from error

    return PreparedNLTask(instruction=instruction, task=task, grounded=grounded, plan=plan)


def prepare_nl_tasks(instructions: List[str], objects_path: str | Path) -> List[PreparedNLTask]:
    """Preflight a sequence before any scene reset or robot motion begins.

    The current object table is static.  Therefore one physical object cannot
    safely be used as the target twice in one sequence: after the first task,
    its real RViz pose differs from the pose stored in ``objects.json``.
    """
    prepared_tasks: List[PreparedNLTask] = []
    seen_target_ids: Dict[str, int] = {}
    for index, instruction in enumerate(instructions, start=1):
        prepared = prepare_nl_task(instruction, objects_path)
        target_id = prepared.grounded["target"].object_id
        if target_id in seen_target_ids:
            first_index = seen_target_ids[target_id]
            raise NLTaskError(
                "Sequence validation failed",
                f"task {index} reuses target '{target_id}' from task {first_index}; "
                "the current sequence runner supports each target only once",
            )
        seen_target_ids[target_id] = index
        prepared_tasks.append(prepared)
    return prepared_tasks


def print_prepared_task(prepared: PreparedNLTask) -> None:
    """Print the inspectable NL-to-skill handoff used in the course demo."""
    print(f"Instruction: {prepared.instruction}")
    print("Parsed DSL:")
    print(json.dumps(prepared.task, ensure_ascii=False, indent=2))
    print("Validation: valid")
    print_grounding("target", prepared.task["target"], prepared.grounded["target"])
    print_grounding("destination", prepared.task["destination"], prepared.grounded["destination"])
    print("Skills: " + " -> ".join(skill.name for skill in prepared.plan))


def execute_prepared_tasks(
    prepared_tasks: List[PreparedNLTask],
    *,
    execute: bool,
    reset_scene: bool,
    objects_path: str,
    client_script: str,
    scene_manager_script: str,
    manipulation_params_path: str,
    gripper_link: Optional[str],
) -> bool:
    """Reset once, then dispatch already-prepared tasks in their input order."""
    if not prepared_tasks:
        raise ValueError("At least one prepared task is required.")

    executor = ArmExecutor(
        execute=execute,
        client_script=client_script,
        scene_manager_script=scene_manager_script,
        objects_path=objects_path,
        manipulation_params_path=manipulation_params_path,
        gripper_link=gripper_link,
    )
    if reset_scene:
        executor.reset_scene()

    for index, prepared in enumerate(prepared_tasks, start=1):
        print(f"===== Execute task {index}/{len(prepared_tasks)} =====")
        executor.execute_skill_plan(prepared.plan, prepared.grounded, prepared.task["relation"])
    return True


def execute_prepared_task(
    prepared: PreparedNLTask,
    *,
    execute: bool,
    reset_scene: bool,
    objects_path: str,
    client_script: str,
    scene_manager_script: str,
    manipulation_params_path: str,
    gripper_link: Optional[str],
) -> bool:
    """Backward-compatible single-task wrapper around sequence execution."""
    return execute_prepared_tasks(
        [prepared],
        execute=execute,
        reset_scene=reset_scene,
        objects_path=objects_path,
        client_script=client_script,
        scene_manager_script=scene_manager_script,
        manipulation_params_path=manipulation_params_path,
        gripper_link=gripper_link,
    )


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Run one Chinese instruction with the Panda arm.")
    parser.add_argument(
        "instructions",
        nargs="+",
        help="One or more instructions, for example: 请把红色积木放到蓝色盒子里面",
    )
    parser.add_argument("--execute", action="store_true", help="Execute MoveIt commands instead of dry-run.")
    reset_group = parser.add_mutually_exclusive_group()
    reset_group.add_argument("--reset-scene", dest="reset_scene", action="store_true")
    reset_group.add_argument("--no-reset-scene", dest="reset_scene", action="store_false")
    parser.set_defaults(reset_scene=True)
    parser.add_argument("--objects", default=root / "configs" / "objects.json")
    parser.add_argument("--client-script", default=root / "src" / "panda_moveit_client.py")
    parser.add_argument("--scene-manager-script", default=root / "src" / "scene_manager.py")
    parser.add_argument("--manipulation-params", default=root / "configs" / "manipulation_params.json")
    parser.add_argument("--gripper-link")
    args = parser.parse_args()

    try:
        prepared_tasks = prepare_nl_tasks(args.instructions, args.objects)
        for index, prepared in enumerate(prepared_tasks, start=1):
            if len(prepared_tasks) > 1:
                print(f"===== Prepared task {index}/{len(prepared_tasks)} =====")
            print_prepared_task(prepared)
        execute_prepared_tasks(
            prepared_tasks,
            execute=args.execute,
            reset_scene=args.reset_scene,
            objects_path=str(args.objects),
            client_script=str(args.client_script),
            scene_manager_script=str(args.scene_manager_script),
            manipulation_params_path=str(args.manipulation_params),
            gripper_link=args.gripper_link,
        )
    except NLTaskError as error:
        parser.exit(2, f"{error.stage}: {error.reason}\n")


if __name__ == "__main__":
    main()
