# Language-Guided Panda Arm

A course-project prototype for a language-guided Panda pick-and-place task in
ROS 2 Jazzy and MoveIt 2. The current demonstration pipeline is:

`task DSL -> object grounding -> skill plan -> object-aware poses -> MoveIt 2`

During a demonstration, the target object is attached to and released from the
MoveIt Planning Scene, so its state is visible in RViz. Gripper opening and
closing are intentionally logged rather than sent to a physical gripper.

## Prerequisites

- Ubuntu 24.04
- ROS 2 Jazzy
- `moveit_resources_panda_moveit_config`
- `pymoveit2` available to the Python used by `python3`

## Run The RViz Demonstration

Start the Panda MoveIt demo in one terminal:

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch moveit_resources_panda_moveit_config demo.launch.py
```

In a second terminal, run the complete task:

```bash
cd ~/my/language-guided-panda-arm
source /opt/ros/jazzy/setup.bash
python3 src/arm_executor.py \
  --task-file configs/demo_pick_place.json \
  --execute
```

The executor resets the managed Planning Scene by default, then performs:

`home -> pre-grasp -> grasp -> attach -> lift -> pre-place -> place -> release -> home`

Use `--no-reset-scene` only when deliberately keeping a manually edited scene.
Omit `--execute` to inspect the grounded objects, skill plan, and generated
MoveIt commands without moving the arm.

## Project Layout

- `configs/objects.json`: shared semantic, geometric, and Planning Scene object table
- `configs/demo_pick_place.json`: task DSL used in the demo
- `configs/manipulation_params.json`: robot-specific pose and gripper calibration
- `src/object_grounder.py`: resolves DSL references to concrete object IDs
- `src/skill_planner.py`: creates the explicit pick-and-place skill sequence
- `src/manipulation_geometry.py`: computes grasp and placement poses from geometry
- `src/scene_manager.py`: adds, attaches, places, and clears RViz/MoveIt objects
- `src/panda_moveit_client.py`: executes one arm joint or pose goal
- `src/arm_executor.py`: end-to-end orchestrator

## Current Scope

This first-week version supports the `pick_place` intent with the `in` and
`on` placement relations. It uses a fixed top-down orientation configured in
`manipulation_params.json`. Its current `grasp_center_to_tcp` value is the
standard Panda `panda_link8` to finger-center offset for the configured
top-down orientation. Calibrate it again before using different hardware, then
replace the logged gripper actions.