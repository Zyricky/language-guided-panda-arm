#!/usr/bin/env python3
'''
测试：
    cd ~/my/language-guided-panda-arm
    python3 src/arm_executor.py --task-file configs/demo_pick_place.json

执行：加--execute
    cd ~/my/language-guided-panda-arm
    source /opt/ros/jazzy/setup.bash
    python3 src/arm_executor.py --task-file configs/demo_pick_place.json --execute
'''

import argparse
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from typing import Any, Dict, List, Optional

from manipulation_geometry import (
    ManipulationPoseGenerator,
    PickPlaceGeometry,
    Pose3D,
    load_manipulation_parameters,
)
from object_grounder import GroundedObject, GroundingError, ObjectGrounder, print_grounding
from skill_planner import PlanningError, Skill, SkillPlanner, load_tasks, print_plan


class ExecutionError(RuntimeError):
    """Raised when a symbolic skill plan cannot be executed safely."""


@dataclass(frozen=True)
class PreparedStructuredTask:
    """One JSON task after grounding and symbolic planning."""

    task: Dict[str, Any]
    grounded: Dict[str, GroundedObject]
    plan: List[Skill]


def _task_label(task: Dict[str, Any], index: int) -> str:
    task_id = task.get("id")
    return f"task {index} ({task_id})" if task_id else f"task {index}"


def prepare_structured_tasks(
    tasks: List[Dict[str, Any]], objects_path: str | Path
) -> List[PreparedStructuredTask]:
    """Preflight a JSON task sequence before resetting the scene or moving the arm."""
    if not tasks:
        raise ExecutionError("At least one task is required.")

    grounder = ObjectGrounder(str(objects_path))
    planner = SkillPlanner()
    prepared_tasks: List[PreparedStructuredTask] = []
    seen_target_ids: Dict[str, int] = {}

    for index, task in enumerate(tasks, start=1):
        try:
            grounded = grounder.ground_task(task)
            plan = planner.plan(task, grounded)
        except (GroundingError, PlanningError) as error:
            raise ExecutionError(f"Cannot prepare {_task_label(task, index)}: {error}") from error

        target_id = grounded["target"].object_id
        if target_id in seen_target_ids:
            raise ExecutionError(
                f"{_task_label(task, index)} reuses target '{target_id}' from "
                f"task {seen_target_ids[target_id]}; each target can be moved only once per sequence."
            )
        seen_target_ids[target_id] = index
        prepared_tasks.append(PreparedStructuredTask(task, grounded, plan))

    return prepared_tasks


def print_prepared_structured_task(prepared: PreparedStructuredTask) -> None:
    """Print one preflighted JSON task before execution starts."""
    print_grounding("target", prepared.task["target"], prepared.grounded["target"])
    print_grounding("destination", prepared.task["destination"], prepared.grounded["destination"])
    print_plan(prepared.plan)


class ArmExecutor:
    """
    High-level arm skill executor for the NL2Manip project.

    Current demonstration version:
    - Arm motion: call MoveIt2 / pymoveit2 pose-goal or joint-goal demo.
    - Gripper: log simulation only.
    - Object attachment/release: synchronized to the MoveIt Planning Scene.
    - Skill dispatch: execute the explicit plan from ``skill_planner.py``.

    Later versions can replace _run_pose_goal() with native MoveItPy or a ROS2 action client.
    """

    def __init__(
            self, 
            execute: bool = False, 
            sleep_time: float = 1.0,
            client_script: str = os.path.join(os.path.dirname(__file__), "./panda_moveit_client.py"),
            scene_manager_script: str = os.path.join(os.path.dirname(__file__), "./scene_manager.py"),
            objects_path: str = os.path.join(os.path.dirname(__file__), "../configs/objects.json"),
            manipulation_params_path: str = os.path.join(
                os.path.dirname(__file__), "../configs/manipulation_params.json"
            ),
            gripper_link: Optional[str] = None,
        ):
        self.execute = execute
        self.sleep_time = sleep_time

        self.default_quat_xyzw = [1.0, 0.0, 0.0, 0.0]

        self.client_script = os.path.expanduser(client_script)
        self.scene_manager_script = os.path.expanduser(scene_manager_script)
        self.objects_path = os.path.expanduser(objects_path)

        self.manipulation_params_path = os.path.expanduser(manipulation_params_path)
        # 读取抓取几何参数，并据此创建位姿生成器
        self.manipulation_parameters = load_manipulation_parameters(
            self.manipulation_params_path
        )
        self.pose_generator = ManipulationPoseGenerator(self.manipulation_parameters)
        
        # 设置机器人与 MoveIt2 参数
        self.group_name = "panda_arm"
        self.base_link_name = "panda_link0"
        self.end_effector_name = self.manipulation_parameters.motion_link   # 用于运动规划的末端 link，通常为 panda_link8
        self.gripper_link = gripper_link or self.manipulation_parameters.attachment_link    # Planning Scene 中物体附着到哪个夹爪/末端 link
        self.planner_id = "RRTConnectkConfigDefault"        # MoveIt 的规划器 ID
        self.default_quat_xyzw = list(self.manipulation_parameters.top_down_quat_xyzw)  #最后一行将默认姿态替换成配置文件的 top-down 四元数？？为啥

        # 在真实执行模式下做的检查
        if self.execute and shutil.which("python3") is None:
            raise RuntimeError("python3 command not found.")
        
        if self.execute and not os.path.exists(self.client_script):
            raise RuntimeError(f"file not found: {self.client_script}")
        if self.execute and not os.path.exists(self.scene_manager_script):
            raise RuntimeError(f"file not found: {self.scene_manager_script}")
        if self.execute and not os.path.exists(self.objects_path):
            raise RuntimeError(f"Object table not found: {self.objects_path}")

    def _log(self, msg: str):
        print(f"[ArmExecutor] {msg}", flush=True)

    def _run(self, cmd: List[str]):
        self._log("CMD: " + " ".join(cmd))

        if not self.execute:
            # dry-run 的核心：不运行子进程，直接假设成功并返回 True
            self._log("dry-run mode: command not executed")
            return True

        # 真实执行外部命令
        result = subprocess.run(cmd)
        # 执行结果检查
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
        if result.returncode != 0:
            raise RuntimeError(f"Command failed with return code {result.returncode}")
        if os.path.samefile(os.path.abspath(cmd[1]), os.path.abspath(self.client_script)):
            failure_markers = (
                "Planning failed!",
                "Cannot execute motion because the provided/planned trajectory is invalid.",
                "Cannot wait until motion is executed (no motion is in progress).",
            )
            command_output = f"{result.stdout}\n{result.stderr}"
            if any(marker in command_output for marker in failure_markers):
                raise ExecutionError(
                    "MoveIt failed to plan or execute the current motion; "
                    "the remaining manipulation skills were not run."
                )
        return True

    # 以“末端位姿目标”控制机械臂
    def _run_pose_goal(self, 
                       name: str,                   # 日志中的动作名
                       pose: Pose3D,                # 目标位置
                       quat_xyzw=None,              # 末端姿态
                       cartesian: bool = False):    # 是否要求笛卡尔直线规划 
        
        # 没有单独传入四元数时，使用配置中的默认 top-down 姿态。
        quat_xyzw = quat_xyzw or self.default_quat_xyzw

        # 打印当前动作、规划组、位置、姿态、是否笛卡尔路径
        self._log(
            f"{name}: group={self.group_name}, position={pose.as_list()}, quat_xyzw={quat_xyzw}, cartesian={cartesian}"
        )

        # 构造 ROS 2 参数命令，panda_moveit_client.py 再读取这些 ROS 参数，进行 MoveIt2 规划与执行
        cmd = [
            "python3", self.client_script,
            "--ros-args",
            "-p", "mode:=pose",
            "-p", f"group_name:={self.group_name}",
            "-p", f"base_link_name:={self.base_link_name}",
            "-p", f"end_effector_name:={self.end_effector_name}",
            "-p", f"planner_id:={self.planner_id}",
            "-p", f"position:={pose.as_list()}",
            "-p", f"quat_xyzw:={quat_xyzw}",
            "-p", f"cartesian:={str(cartesian)}",
        ]

        # 调用 _run(cmd)，根据 execute 决定真实运行或仅打印
        return self._run(cmd)

    # 发送 7 个关节角，而不是末端的笛卡尔位置与姿态，Home 位姿使用关节目标，因为比“末端位置目标”更确定，也更适合作为固定安全姿态
    def _run_joint_goal(self, name: str, joint_positions: List[float]):
        self._log(
            f"{name}: group={self.group_name}, joint_positions={joint_positions}"
        )

        cmd = [
            "python3", self.client_script,
            "--ros-args",
            "-p", "mode:=joint",
            "-p", f"group_name:={self.group_name}",
            "-p", f"base_link_name:={self.base_link_name}",
            "-p", f"end_effector_name:={self.end_effector_name}",
            "-p", f"planner_id:={self.planner_id}",
            "-p", f"joint_positions:={joint_positions}",
        ]
        return self._run(cmd)

    # Planning Scene 操作
    def _run_scene_manager(self, arguments: List[str]):
        """Apply one dynamic object-state update to the MoveIt Planning Scene."""
        # 统一调用 scene_manager.py
        return self._run(
            [
                "python3",
                self.scene_manager_script,
                "--objects",
                self.objects_path,
                *arguments,
            ]
        )

    # 重置 Planning Scene
    def reset_scene(self):
        """Restore configured objects before a fresh end-to-end demonstration."""
        self._log("Resetting Planning Scene from objects.json")
        return self._run_scene_manager(["--reset"])

    # 在最后靠近目标物时，允许“目标物体”和“夹爪 link”接触
    def allow_grasp_collision(self, object_id: str):
        """Allow only the target and gripper links to touch during final approach."""
        return self._run_scene_manager(
            ["--allow-grasp-collision", object_id, "--gripper-link", self.gripper_link]
        )

    # 放置后恢复普通碰撞规则。之后夹爪若再触碰该物体，会重新被 MoveIt 检测为碰撞
    def restore_grasp_collision(self, object_id: str):
        """Restore normal collision checking after releasing the target."""
        return self._run_scene_manager(
            ["--disallow-grasp-collision", object_id, "--gripper-link", self.gripper_link]
        )

    # -------------------------
    # High-level skills
    # -------------------------

    def move_to_home(self):
        """
        Move to a safe home-like joint configuration.
        The exact configuration is not physically important for the course demo.
        """
        # 实际执行中它很重要：必须是一个无碰撞、可达、适合作为起始/结束状态的姿态。
        home_joints = [0.0, -0.7854, 0.0, -2.3562, 0.0, 1.5708, 0.7854] # 定义固定的 Panda 七关节 home 姿态
        return self._run_joint_goal("MoveToHome", home_joints)

    # 直接使用 geometry 中预先算好的
    def move_to_pre_grasp(self, geometry: PickPlaceGeometry):
        # 抓取点上方的安全接近位置
        return self._run_pose_goal("MoveToPreGrasp", geometry.pre_grasp_tcp_pose)

    def move_to_grasp(self, geometry: PickPlaceGeometry):
        # 真正闭合夹爪的位置
        return self._run_pose_goal("MoveToGrasp", geometry.grasp_tcp_pose)

    def close_gripper(self, object_id: str, opening: float):
        # 打印夹爪闭合日志，物理夹爪尚未真正控制
        self._log(f"[Gripper] close (target opening={opening:.3f} m; log simulation)")
        # 调用 scene_manager.py --attach，让 MoveIt 把目标物体标记为“附着在夹爪上”
        self._run_scene_manager(
            ["--attach", object_id, "--gripper-link", self.gripper_link]
        )
        self._log(f"[Object attached] {object_id}")
        return True

    # 运动到 lift_tcp_pose，即抓住物体后向上撤离
    def lift(self, geometry: PickPlaceGeometry):
        return self._run_pose_goal("Lift", geometry.lift_tcp_pose)

    # 放置点上方安全位置
    def move_to_pre_place(self, geometry: PickPlaceGeometry):
        return self._run_pose_goal("MoveToPrePlace", geometry.pre_place_tcp_pose)

    # 真正放置位置
    def move_to_place(self, geometry: PickPlaceGeometry):
        return self._run_pose_goal("MoveToPlace", geometry.place_tcp_pose)

    # Planning Scene 物体释放
    def open_gripper(
        self,
        object_id: str,
        destination_id: str,
        placement_pose: Pose3D,
    ):
        self._log(f"[Gripper] open")
        # placement_pose.as_list() 得到三维位置；生成器表达的通常是物体中心的位置，不是 TCP 的位置
        self._run_scene_manager(
            [
                "--place",
                object_id,
                "--position",
                *(str(value) for value in placement_pose.as_list()),    
                "--gripper-link",
                self.gripper_link,
            ]
        )
        self._log(f"[Object released] {object_id} at {destination_id}")
        self.restore_grasp_collision(object_id)
        return True

    def return_home(self):
        return self.move_to_home()

    @staticmethod
    def _skill_object(skill: Skill, objects: Dict[str, GroundedObject]) -> GroundedObject:
        # 校验某个技能是否携带了一个正确的 grounding 对象 ID
        if len(skill.arguments) != 1:
            raise ExecutionError(
                f"{skill.name} requires exactly one grounded object ID, got {skill.arguments}."
            )
        object_id = skill.arguments[0]
        try:
            return objects[object_id]
        except KeyError as error:
            raise ExecutionError(
                f"{skill.name} refers to unknown grounded object '{object_id}'."
            ) from error

    # 整个执行器的核心入口
    def execute_skill_plan(
        self,
        plan: List[Skill],  # 技能规划器输出的 List[Skill]
        grounded: Dict[str, GroundedObject],    # 至少包含 target 和 destination
        relation: str,  # 如 in、on，决定最终放置几何
    ) -> bool:
        """Execute a Day-5 skill plan using the grounded scene objects.

        Skills remain object-level symbols until this boundary. Here each object
        ID is resolved to its pose, then dispatched to the existing MoveIt or
        simulated-gripper primitives.
        """
        target = grounded.get("target")
        destination = grounded.get("destination")
        if target is None or destination is None:
            raise ExecutionError("A skill plan needs grounded target and destination objects.")

        objects = {
            target.object_id: target,
            destination.object_id: destination,
        }
        # 生成一整套几何位姿
        geometry = self.pose_generator.generate(target, destination, relation)

        # 打印本次任务的可解释日志
        self._log("===== Execute Pick-and-Place =====")
        self._log(f"Target object: {target.object_id}, pose={Pose3D(*target.position).as_list()}")
        self._log(
            f"Destination: {destination.object_id}, pose={Pose3D(*destination.position).as_list()}"
        )
        self._log(
            f"Grasp center: {geometry.grasp_object_center.as_list()}, "
            f"TCP grasp pose: {geometry.grasp_tcp_pose.as_list()}, "
            f"opening={geometry.recommended_gripper_opening:.3f} m"
        )
        self._log(
            f"Placement center: {geometry.placement_object_center.as_list()}, "
            f"TCP place pose: {geometry.place_tcp_pose.as_list()}, relation={relation}"
        )

        # 逐个执行技能
        for step, skill in enumerate(plan, start=1):
            self._log(f"Skill {step}/{len(plan)}: {skill.format()}")

            if skill.name == "MoveToHome":
                if skill.arguments:
                    raise ExecutionError("MoveToHome does not accept arguments.")
                self.move_to_home()
            elif skill.name == "MoveToPreGrasp":
                self._skill_object(skill, objects)
                self.move_to_pre_grasp(geometry)
            elif skill.name == "MoveToGrasp":
                self._skill_object(skill, objects)
                self.allow_grasp_collision(target.object_id)
                self.move_to_grasp(geometry)
            elif skill.name == "CloseGripper":
                if skill.arguments:
                    raise ExecutionError("CloseGripper does not accept arguments.")
                self.close_gripper(target.object_id, geometry.recommended_gripper_opening)
            elif skill.name == "Lift":
                if skill.arguments:
                    raise ExecutionError("Lift does not accept arguments.")
                self.lift(geometry)
            elif skill.name == "MoveToPrePlace":
                self._skill_object(skill, objects)
                self.move_to_pre_place(geometry)
            elif skill.name == "MoveToPlace":
                self._skill_object(skill, objects)
                self.move_to_place(geometry)
            elif skill.name == "OpenGripper":
                if skill.arguments:
                    raise ExecutionError("OpenGripper does not accept arguments.")
                self.open_gripper(
                    target.object_id,
                    destination.object_id,
                    geometry.placement_object_center,
                )
            elif skill.name == "ReturnHome":
                if skill.arguments:
                    raise ExecutionError("ReturnHome does not accept arguments.")
                self.return_home()
            else:
                raise ExecutionError(f"Unsupported skill '{skill.name}'.")

        self._log("Execution: success")
        return True


def main():
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute MoveIt2 commands. Without this flag, only dry-run.",
    )
    scene_reset = parser.add_mutually_exclusive_group()
    scene_reset.add_argument(
        "--reset-scene",
        dest="reset_scene",
        action="store_true",
        help="Clear stale scene state and restore objects.json before executing the task (default).",
    )
    scene_reset.add_argument(
        "--no-reset-scene",
        dest="reset_scene",
        action="store_false",
        help="Keep the current Planning Scene instead of restoring configs/objects.json.",
    )
    parser.set_defaults(reset_scene=True)
    parser.add_argument(
        "--client-script",
        default=os.path.join(os.path.dirname(__file__), "./panda_moveit_client.py"),
        help="Path to panda_moveit_client.py",
    )
    parser.add_argument(
        "--scene-manager-script",
        default=os.path.join(os.path.dirname(__file__), "./scene_manager.py"),
        help="Path to scene_manager.py for attach/place scene updates.",
    )
    parser.add_argument(
        "--manipulation-params",
        default=project_root / "configs" / "manipulation_params.json",
        help="Path to robot calibration and motion-clearance parameters.",
    )
    parser.add_argument(
        "--gripper-link",
        help="Override the configured Planning Scene attachment link.",
    )
    parser.add_argument(
        "--objects",
        default=project_root / "configs" / "objects.json",
        help="Path to the scene object table.",
    )
    parser.add_argument(
        "--task-file",
        help="Path to one task DSL or a {\"tasks\": [...]} task-sequence JSON file.",
    )
    args = parser.parse_args()

    tasks = load_tasks(args.task_file)
    prepared_tasks = prepare_structured_tasks(tasks, args.objects)
    for index, prepared in enumerate(prepared_tasks, start=1):
        if len(prepared_tasks) > 1:
            print(f"===== Prepared {_task_label(prepared.task, index)} =====")
        print_prepared_structured_task(prepared)

    executor = ArmExecutor(
        execute=args.execute,
        client_script=args.client_script,
        scene_manager_script=args.scene_manager_script,
        objects_path=args.objects,
        manipulation_params_path=args.manipulation_params,
        gripper_link=args.gripper_link,
    )
    if args.reset_scene:
        executor.reset_scene()
    for index, prepared in enumerate(prepared_tasks, start=1):
        if len(prepared_tasks) > 1:
            print(f"===== Execute {_task_label(prepared.task, index)} =====")
        executor.execute_skill_plan(
            prepared.plan,
            prepared.grounded,
            prepared.task["relation"],
        )


if __name__ == "__main__":
    main()
