#!/usr/bin/env python3
"""Convert a grounded task DSL into an explicit, inspectable skill plan."""
# 文件顶层说明：将已落地的任务 DSL 转为技能序列

import argparse                      # 处理命令行参数
import json                          # 读取 task JSON
from dataclasses import dataclass    # 定义不可变/轻量数据对象
from pathlib import Path             # 文件路径处理
from typing import Any, Dict, List, Optional  # 类型注解

from object_grounder import GroundedObject, ObjectGrounder, print_grounding
# 从同目录模块导入 GroundedObject、ObjectGrounder、print_grounding 用于对象落地与打印

class PlanningError(ValueError):
    """Raised when a grounded task cannot be converted into a skill plan."""
    # 自定义异常类型：当无法规划时抛出

@dataclass(frozen=True)
class Skill:
    """One named robot skill with optional grounded object arguments."""
    # Skill 表示一个高层动作（名称 + 绑定的对象 id 列表）
    name: str
    arguments: List[str]

    def format(self) -> str:
        # 将 Skill 转为可打印的字符串形式，比如 "MoveToGrasp(obj_3)"
        if not self.arguments:
            return self.name
        return f"{self.name}({', '.join(self.arguments)})"

class SkillPlanner:
    """Initial symbolic planner for the supported manipulation task DSL.

    The planner deliberately does not contain poses or motion details. Its output
    names high-level skills and binds them to concrete scene object IDs; the
    executor remains responsible for turning those skills into MoveIt commands.
    """
    # SkillPlanner 只做符号级规划（不涉及位姿、路径），把抽象任务映射为有对象参数的技能序列

    def plan(self, task: Dict[str, Any], grounded: Dict[str, GroundedObject]) -> List[Skill]:
        # 生成技能序列的主函数，接收原始 task（DSL）和落地结果（映射名->GroundedObject）
        if task.get("intent") != "pick_place":
            # 目前只支持 pick_place 意图，其他意图抛出错误
            raise PlanningError("Only the 'pick_place' intent is supported.")

        target = grounded.get("target")         # 从落地结果获取目标对象
        destination = grounded.get("destination")  # 获取放置目标对象
        if target is None or destination is None:
            # 如果缺少任一对象则无法规划
            raise PlanningError("A pick_place plan requires grounded target and destination objects.")

        # 返回固定顺序的技能列表，部分技能绑定具体对象 id（通过 grounded.object_id）
        return [
            Skill("MoveToHome", []),
            Skill("MoveToPreGrasp", [target.object_id]),
            Skill("MoveToGrasp", [target.object_id]),
            Skill("CloseGripper", []),
            Skill("Lift", []),
            Skill("MoveToPrePlace", [destination.object_id]),
            Skill("MoveToPlace", [destination.object_id]),
            Skill("OpenGripper", []),
            Skill("ReturnHome", []),
        ]

def print_plan(plan: List[Skill]) -> None:
    """Print the Day-5 skill sequence, one skill per line."""
    # 将生成的技能序列按行打印，便于人工检查
    print("Skill plan:")
    for index, skill in enumerate(plan, start=1):
        print(f"{index}. {skill.format()}")  # 使用 Skill.format() 输出每一步

def load_tasks(task_file: Optional[str]) -> List[Dict[str, Any]]:
    """Load either one task DSL or a ``{"tasks": [...]}`` task sequence."""
    if task_file:
        with Path(task_file).expanduser().open(encoding="utf-8") as file:
            document = json.load(file)
        if not isinstance(document, dict):
            raise ValueError("Task file must contain a JSON object.")
        if "tasks" in document:
            tasks = document["tasks"]
            if not isinstance(tasks, list) or not tasks:
                raise ValueError("'tasks' must be a non-empty JSON list.")
            if not all(isinstance(task, dict) for task in tasks):
                raise ValueError("Every item in 'tasks' must be a JSON object.")
            return tasks
        return [document]

    return [{
        "intent": "pick_place",
        "target": {"type": "cube", "color": "red"},
        "destination": {"type": "box", "color": "blue"},
        "relation": "in",
    }]


def load_task(task_file: Optional[str]) -> Dict[str, Any]:
    """Load exactly one task, preserving the original single-task API."""
    tasks = load_tasks(task_file)
    if len(tasks) != 1:
        raise ValueError("Task file contains multiple tasks; use load_tasks() for a sequence.")
    return tasks[0]

def main() -> None:
    root = Path(__file__).resolve().parent.parent
    # root 指向项目根目录（当前文件的上一级目录）
    parser = argparse.ArgumentParser(
        description="Ground a task DSL and generate its high-level skill sequence."
    )
    parser.add_argument(
        "--task-file",
        default=root / "configs" / "demo_pick_place.json",
        help="Path to one task DSL or a {\"tasks\": [...]} task-sequence JSON file.",
    )
    parser.add_argument(
        "--objects",
        default=root / "configs" / "objects.json",
        help="Path to the scene object table.",
    )
    args = parser.parse_args()

    tasks = load_tasks(str(args.task_file) if args.task_file else None)
    grounder = ObjectGrounder(args.objects)
    planner = SkillPlanner()
    for index, task in enumerate(tasks, start=1):
        if len(tasks) > 1:
            print(f"===== Task {index}/{len(tasks)} =====")
        grounded = grounder.ground_task(task)
        print_grounding("target", task["target"], grounded["target"])
        print_grounding("destination", task["destination"], grounded["destination"])
        print_plan(planner.plan(task, grounded))

if __name__ == "__main__":
    main()
