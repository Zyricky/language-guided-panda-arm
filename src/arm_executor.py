#!/usr/bin/env python3
'''
测试：
    cd ~/my/nlp-demo
    python3 src/arm_executor.py

执行：加--execute
    cd ~/my/nlp-demo
    source /opt/ros/jazzy/setup.bash
    python3 src/arm_executor.py --execute
'''

import argparse
import os
import shutil
import subprocess
import time

from dataclasses import dataclass
from typing import List


@dataclass
class Pose3D:
    x: float
    y: float
    z: float

    def shifted(self, dx=0.0, dy=0.0, dz=0.0):
        return Pose3D(self.x + dx, self.y + dy, self.z + dz)

    def as_list(self):
        return [round(self.x, 4), round(self.y, 4), round(self.z, 4)]


class ArmExecutor:
    """
    High-level arm skill executor for the NL2Manip project.

    Current Day-2 version:
    - Arm motion: call MoveIt2 / pymoveit2 pose-goal or joint-goal demo.
    - Gripper: log simulation only.
    - Object attachment/release: log simulation only.

    Later versions can replace _run_pose_goal() with native MoveItPy or a ROS2 action client.
    """

    def __init__(
            self, 
            execute: bool = False, 
            sleep_time: float = 0.8,
            client_script: str = os.path.join(os.path.dirname(__file__), "./panda_moveit_client.py"),
        ):
        self.execute = execute
        self.sleep_time = sleep_time

        self.default_quat_xyzw = [1.0, 0.0, 0.0, 0.0]

        self.client_script = os.path.expanduser(client_script)

        self.group_name = "panda_arm"
        self.base_link_name = "panda_link0"
        self.end_effector_name = "panda_link8"
        self.planner_id = "RRTConnectkConfigDefault"

        if self.execute and shutil.which("python3") is None:
            raise RuntimeError("python3 command not found.")
        
        if self.execute and not os.path.exists(self.client_script):
            raise RuntimeError(f"file not found: {self.client_script}")

    def _log(self, msg: str):
        print(f"[ArmExecutor] {msg}", flush=True)

    def _run(self, cmd: List[str]):
        self._log("CMD: " + " ".join(cmd))

        if not self.execute:
            self._log("dry-run mode: command not executed")
            return True

        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Command failed with return code {result.returncode}")
        time.sleep(self.sleep_time)
        return True

    def _run_pose_goal(self, name: str, pose: Pose3D, quat_xyzw=None, cartesian: bool = False):
        quat_xyzw = quat_xyzw or self.default_quat_xyzw

        self._log(
            f"{name}: group={self.group_name}, position={pose.as_list()}, quat_xyzw={quat_xyzw}, cartesian={cartesian}"
        )

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
        return self._run(cmd)

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

    # -------------------------
    # High-level skills
    # -------------------------

    def move_to_home(self):
        """
        Move to a safe home-like joint configuration.
        The exact configuration is not physically important for the course demo.
        """
        home_joints = [0.0, -0.7854, 0.0, -2.3562, 0.0, 1.5708, 0.7854]
        return self._run_joint_goal("MoveToHome", home_joints)

    def move_to_pre_grasp(self, object_pose: Pose3D):
        """
        Move above the object.
        We intentionally keep z high to avoid early collision/debug problems.
        """
        pre_grasp_pose = object_pose.shifted(dz=0.35)
        pre_grasp_pose.z = max(pre_grasp_pose.z, 0.42)
        return self._run_pose_goal("MoveToPreGrasp", pre_grasp_pose)

    def move_to_grasp(self, object_pose: Pose3D):
        """
        Move closer to the object.
        This is still a fake grasp pose, not real contact grasping.
        """
        grasp_pose = object_pose.shifted(dz=0.22)
        grasp_pose.z = max(grasp_pose.z, 0.28)
        return self._run_pose_goal("MoveToGrasp", grasp_pose)

    def close_gripper(self, object_id: str = "object"):
        self._log(f"[Gripper] close")
        self._log(f"[Object attached] {object_id}")
        time.sleep(self.sleep_time)
        return True

    def lift(self, object_pose: Pose3D):
        lift_pose = object_pose.shifted(dz=0.45)
        lift_pose.z = max(lift_pose.z, 0.50)
        return self._run_pose_goal("Lift", lift_pose)

    def move_to_pre_place(self, destination_pose: Pose3D):
        pre_place_pose = destination_pose.shifted(dz=0.40)
        pre_place_pose.z = max(pre_place_pose.z, 0.45)
        return self._run_pose_goal("MoveToPrePlace", pre_place_pose)

    def move_to_place(self, destination_pose: Pose3D):
        place_pose = destination_pose.shifted(dz=0.25)
        place_pose.z = max(place_pose.z, 0.32)
        return self._run_pose_goal("MoveToPlace", place_pose)

    def open_gripper(self, object_id: str = "object", destination_id: str = "destination"):
        self._log(f"[Gripper] open")
        self._log(f"[Object released] {object_id} at {destination_id}")
        time.sleep(self.sleep_time)
        return True

    def return_home(self):
        return self.move_to_home()

    def execute_pick_place(
        self,
        object_id: str,
        object_pose: Pose3D,
        destination_id: str,
        destination_pose: Pose3D,
    ):
        self._log("===== Execute Pick-and-Place =====")
        self._log(f"Target object: {object_id}, pose={object_pose.as_list()}")
        self._log(f"Destination: {destination_id}, pose={destination_pose.as_list()}")

        self.move_to_home()
        self.move_to_pre_grasp(object_pose)
        self.move_to_grasp(object_pose)
        self.close_gripper(object_id)
        self.lift(object_pose)
        self.move_to_pre_place(destination_pose)
        self.move_to_place(destination_pose)
        self.open_gripper(object_id, destination_id)
        self.return_home()

        self._log("Execution: success")
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute MoveIt2 commands. Without this flag, only dry-run.",
    )
    parser.add_argument(
        "--client-script",
        default=os.path.join(os.path.dirname(__file__), "./panda_moveit_client.py"),
        help="Path to panda_moveit_client.py",
    )
    args = parser.parse_args()

    # These poses match our planned object table style.
    # They are not physical grasp contact poses yet; they are safe demo poses.
    red_cube_pose = Pose3D(0.45, 0.20, 0.04)
    blue_box_pose = Pose3D(0.55, -0.20, 0.04)

    executor = ArmExecutor(
        execute=args.execute,
        client_script=args.client_script,
    )
    executor.execute_pick_place(
        object_id="red_cube_1",
        object_pose=red_cube_pose,
        destination_id="blue_box_1",
        destination_pose=blue_box_pose,
    )


if __name__ == "__main__":
    main()