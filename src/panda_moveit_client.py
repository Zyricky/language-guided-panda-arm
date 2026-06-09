#!/usr/bin/env python3

import time

from threading import Thread

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from pymoveit2 import MoveIt2

PANDA_JOINT_NAMES = [
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
]

def main():
    rclpy.init()

    node = Node("panda_moveit_client")

    node.declare_parameter("mode", "joint")
    node.declare_parameter(
        "joint_positions",
        [0.0, -0.7854, 0.0, -2.3562, 0.0, 1.5708, 0.7854],
    )
    node.declare_parameter("position", [0.35, 0.0, 0.55])
    node.declare_parameter("quat_xyzw", [1.0, 0.0, 0.0, 0.0])
    node.declare_parameter("cartesian", False)

    node.declare_parameter("group_name", "panda_arm")
    node.declare_parameter("base_link_name", "panda_link0")
    node.declare_parameter("end_effector_name", "panda_link8")
    node.declare_parameter("planner_id", "RRTConnectkConfigDefault")

    callable_group = ReentrantCallbackGroup()

    group_name = node.get_parameter("group_name").get_parameter_value().string_value
    base_link_name = node.get_parameter("base_link_name").get_parameter_value().string_value
    end_effector_name = node.get_parameter("end_effector_name").get_parameter_value().string_value
    
    moveit2 = MoveIt2(
        node=node,
        joint_names=PANDA_JOINT_NAMES,
        base_link_name=base_link_name,
        end_effector_name=end_effector_name,
        group_name=group_name,
        callback_group=callable_group,
    )

    moveit2.planner_id = node.get_parameter("planner_id").get_parameter_value().string_value
    moveit2.max_velocity = 0.4
    moveit2.max_acceleration = 0.4

    executor = MultiThreadedExecutor(2)
    executor.add_node(node)
    executor_thread = Thread(target=executor.spin, daemon=True)
    executor_thread.start()

    # node.create_rate(1.0).sleep()
    time.sleep(1.0)

    mode = node.get_parameter("mode").get_parameter_value().string_value

    if mode == 'joint':
        joint_positions = (
            node.get_parameter("joint_positions").get_parameter_value().double_array_value
        )
        node.get_logger().info(
            f"Planning with group='{group_name}', joint_positions={list(joint_positions)}"
        )
        moveit2.move_to_configuration(joint_positions)

    elif mode == "pose":
        position = node.get_parameter("position").get_parameter_value().double_array_value
        quat_xyzw = node.get_parameter("quat_xyzw").get_parameter_value().double_array_value
        cartesian = node.get_parameter("cartesian").get_parameter_value().bool_value

        node.get_logger().info(
            f"Planning with group='{group_name}', ee='{end_effector_name}', "
            f"position={list(position)}, quat_xyzw={list(quat_xyzw)}"
        )
        
        moveit2.move_to_pose(
            position=position,
            quat_xyzw=quat_xyzw,
            cartesian=cartesian,
        )

    else:
        raise ValueError(f"Unknown mode: {mode}")
    
    moveit2.wait_until_executed()

    rclpy.shutdown()
    executor_thread.join()


if __name__ == "__main__":
    main()


# 给这个脚本添加可执行权限
# chmod +x ~/my/nlp-demo/src/panda_moveit_client.py
'''
测试 joint goal
python3 ~/my/nlp-demo/src/panda_moveit_client.py \
  --ros-args \
  -p mode:=joint \
  -p group_name:=panda_arm

测试 pose goal
python3 ~/my/nlp-demo/src/panda_moveit_client.py \
  --ros-args \
  -p mode:=pose \
  -p group_name:=panda_arm \
  -p end_effector_name:=panda_link8 \
  -p position:="[0.35, 0.0, 0.55]" \
  -p quat_xyzw:="[1.0, 0.0, 0.0, 0.0]" \
  -p cartesian:=False

'''