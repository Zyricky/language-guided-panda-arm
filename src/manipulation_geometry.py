#!/usr/bin/env python3
"""Generate object-aware pick-and-place poses for the Panda demonstration."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, Tuple

from object_grounder import GroundedObject


class GeometryError(ValueError):
    """Raised when an object cannot be grasped or placed with the configured tool."""


@dataclass(frozen=True)
class Pose3D:
    """A position expressed in the task frame (currently ``panda_link0``)."""

    x: float
    y: float
    z: float

    def shifted(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> "Pose3D":
        return Pose3D(self.x + dx, self.y + dy, self.z + dz)

    def as_list(self) -> list[float]:
        return [round(self.x, 4), round(self.y, 4), round(self.z, 4)]


@dataclass(frozen=True)
class ManipulationParameters:
    """Robot-specific calibration and conservative motion clearances."""

    motion_link: str
    attachment_link: str
    top_down_quat_xyzw: Tuple[float, float, float, float]
    grasp_center_to_tcp: Pose3D
    approach_distance: float
    lift_distance: float
    place_clearance: float
    min_opening: float
    max_opening: float
    object_clearance: float


@dataclass(frozen=True)
class PickPlaceGeometry:
    """Object-aware Cartesian targets for one complete pick-and-place task."""

    grasp_object_center: Pose3D
    grasp_tcp_pose: Pose3D
    pre_grasp_tcp_pose: Pose3D
    lift_tcp_pose: Pose3D
    placement_object_center: Pose3D
    place_tcp_pose: Pose3D
    pre_place_tcp_pose: Pose3D
    recommended_gripper_opening: float


def _numbers(value: Any, count: int, name: str) -> Tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GeometryError(f"{name} must be a list of {count} numbers.")
    if len(value) != count:
        raise GeometryError(f"{name} must contain {count} numbers, got {len(value)}.")
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError) as error:
        raise GeometryError(f"{name} must contain only numbers.") from error


def load_manipulation_parameters(path: str) -> ManipulationParameters:
    """Load robot calibration separately from semantic scene-object data."""
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Manipulation parameters not found: {config_path}")

    with config_path.open(encoding="utf-8") as file:
        data = json.load(file)

    try:
        motion_link = data["motion_link"]
        attachment_link = data["attachment_link"]
        top_down_quat_xyzw = _numbers(data["top_down_quat_xyzw"], 4, "top_down_quat_xyzw")
        tcp_offset = _numbers(data["grasp_center_to_tcp"], 3, "grasp_center_to_tcp")
        gripper = data["gripper"]
        parameters = ManipulationParameters(
            motion_link=str(motion_link),
            attachment_link=str(attachment_link),
            top_down_quat_xyzw=top_down_quat_xyzw,
            grasp_center_to_tcp=Pose3D(*tcp_offset),
            approach_distance=float(data["approach_distance"]),
            lift_distance=float(data["lift_distance"]),
            place_clearance=float(data["place_clearance"]),
            min_opening=float(gripper["min_opening"]),
            max_opening=float(gripper["max_opening"]),
            object_clearance=float(gripper["object_clearance"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise GeometryError(f"Malformed manipulation parameters: {config_path}") from error

    positive_values = {
        "approach_distance": parameters.approach_distance,
        "lift_distance": parameters.lift_distance,
        "place_clearance": parameters.place_clearance,
        "max_opening": parameters.max_opening,
        "object_clearance": parameters.object_clearance,
    }
    if any(value <= 0.0 for value in positive_values.values()):
        raise GeometryError("Motion distances and gripper max opening must be positive.")
    if parameters.min_opening < 0.0 or parameters.min_opening > parameters.max_opening:
        raise GeometryError("Invalid gripper opening range.")
    return parameters


class ManipulationPoseGenerator:
    """Create TCP poses from grounded object geometry and tool calibration.

    The current strategy is a fixed-orientation top-down parallel-jaw grasp of
    upright, axis-aligned objects. Object size determines the required gripper opening
    and final placement center. ``grasp_center_to_tcp`` is a Panda-specific,
    one-time calibration; it is not a per-object world-coordinate constant.
    """

    def __init__(self, parameters: ManipulationParameters):
        self.parameters = parameters

    @classmethod
    def object_height(cls, obj: GroundedObject) -> float:
        size = obj.raw.get("size")
        try:
            height = float(size["height"]) if obj.object_type == "cylinder" else float(size[2])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise GeometryError(f"Malformed size for '{obj.object_id}'.") from error
        if height <= 0.0:
            raise GeometryError(f"'{obj.object_id}' must have positive height.")
        return height

    @classmethod
    def footprint(cls, obj: GroundedObject) -> Tuple[float, float]:
        size = obj.raw.get("size")
        try:
            if obj.object_type == "cylinder":
                diameter = 2.0 * float(size["radius"])
                return diameter, diameter
            x_size, y_size = float(size[0]), float(size[1])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise GeometryError(f"Malformed footprint for '{obj.object_id}'.") from error
        if x_size <= 0.0 or y_size <= 0.0:
            raise GeometryError(f"'{obj.object_id}' must have a positive footprint.")
        return x_size, y_size

    def recommended_gripper_opening(self, target: GroundedObject) -> float:
        """Use the smaller horizontal dimension for a stable side pinch grasp."""
        object_width = min(self.footprint(target))
        opening = object_width + self.parameters.object_clearance
        if opening < self.parameters.min_opening or opening > self.parameters.max_opening:
            raise GeometryError(
                f"'{target.object_id}' needs gripper opening {opening:.3f} m, outside "
                f"[{self.parameters.min_opening:.3f}, {self.parameters.max_opening:.3f}] m."
            )
        return opening

    def placement_object_center(
        self,
        target: GroundedObject,
        destination: GroundedObject,
        relation: str,
    ) -> Pose3D:
        """Compute the final object center without making assumptions about TCP height."""
        target_height = self.object_height(target)
        clearance = self.parameters.place_clearance

        if relation == "on":
            try:
                destination_height = float(destination.raw["size"][2])
            except (IndexError, KeyError, TypeError, ValueError) as error:
                raise GeometryError(f"Malformed support size for '{destination.object_id}'.") from error
            support_top_z = destination.position[2] + destination_height / 2.0
            return Pose3D(
                destination.position[0],
                destination.position[1],
                support_top_z + target_height / 2.0 + clearance,
            )

        if relation != "in":
            raise GeometryError(f"Unsupported placement relation '{relation}'.")

        geometry = destination.raw.get("scene_geometry", {})
        if geometry.get("kind") != "open_container":
            raise GeometryError(f"Destination '{destination.object_id}' is not an open container.")
        try:
            outer_x, outer_y, outer_z = (float(value) for value in destination.raw["size"])
            wall = float(geometry["wall_thickness"])
            bottom = float(geometry["bottom_thickness"])
        except (KeyError, TypeError, ValueError) as error:
            raise GeometryError(
                f"Malformed open-container geometry for '{destination.object_id}'."
            ) from error

        inner_x = outer_x - 2.0 * wall
        inner_y = outer_y - 2.0 * wall
        target_x, target_y = self.footprint(target)
        if target_x + 2.0 * clearance > inner_x or target_y + 2.0 * clearance > inner_y:
            raise GeometryError(f"'{target.object_id}' does not fit inside '{destination.object_id}'.")
        inner_floor_z = destination.position[2] - outer_z / 2.0 + bottom
        return Pose3D(
            destination.position[0],
            destination.position[1],
            inner_floor_z + target_height / 2.0 + clearance,
        )

    def tcp_pose_for_grasp_center(self, grasp_center: Pose3D) -> Pose3D:
        """Translate an object-side grasp center into the configured TCP frame."""
        offset = self.parameters.grasp_center_to_tcp
        return grasp_center.shifted(dx=offset.x, dy=offset.y, dz=offset.z)

    def generate(
        self,
        target: GroundedObject,
        destination: GroundedObject,
        relation: str,
    ) -> PickPlaceGeometry:
        grasp_center = Pose3D(*target.position)
        grasp_tcp_pose = self.tcp_pose_for_grasp_center(grasp_center)
        placement_center = self.placement_object_center(target, destination, relation)
        place_tcp_pose = self.tcp_pose_for_grasp_center(placement_center)

        return PickPlaceGeometry(
            grasp_object_center=grasp_center,
            grasp_tcp_pose=grasp_tcp_pose,
            pre_grasp_tcp_pose=grasp_tcp_pose.shifted(dz=self.parameters.approach_distance),
            lift_tcp_pose=grasp_tcp_pose.shifted(dz=self.parameters.lift_distance),
            placement_object_center=placement_center,
            place_tcp_pose=place_tcp_pose,
            pre_place_tcp_pose=place_tcp_pose.shifted(dz=self.parameters.approach_distance),
            recommended_gripper_opening=self.recommended_gripper_opening(target),
        )
