#!/usr/bin/env python3
"""Synchronize ``configs/objects.json`` into MoveIt's Planning Scene.

Run this after ``demo.launch.py`` starts and before running ``arm_executor.py``.
It adds scene objects both as collision geometry for planning and as colored
geometry in RViz's MotionPlanning / Planning Scene display.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import rclpy
from geometry_msgs.msg import Pose, Quaternion
from moveit_msgs.msg import (
    AttachedCollisionObject,
    AllowedCollisionEntry,
    CollisionObject,
    ObjectColor,
    PlanningScene,
    PlanningSceneComponents,
)
from moveit_msgs.srv import ApplyPlanningScene, GetPlanningScene
from rclpy.node import Node
from rclpy.time import Time
from shape_msgs.msg import SolidPrimitive
from std_msgs.msg import ColorRGBA
from tf2_ros import Buffer, TransformException, TransformListener


DEFAULT_TABLE_SIZE = (1.0, 0.8, 0.04)
COLOR_BY_NAME = {
    "red": (0.9, 0.1, 0.1, 1.0),
    "blue": (0.1, 0.35, 0.95, 0.85),
    "green": (0.1, 0.65, 0.2, 1.0),
    None: (0.55, 0.55, 0.55, 1.0),
}
PANDA_HAND_TOUCH_LINKS = ["panda_hand", "panda_leftfinger", "panda_rightfinger"]


class SceneError(ValueError):
    """Raised when an object table cannot be represented in the planning scene."""


def load_objects(objects_path: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Load and minimally validate the shared grounding / planning object table."""
    path = Path(objects_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Object table not found: {path}")

    with path.open(encoding="utf-8") as file:
        scene = json.load(file)

    frame_id = scene.get("frame_id")
    objects = scene.get("objects")
    if not isinstance(frame_id, str) or not frame_id:
        raise SceneError("Object table requires a non-empty top-level 'frame_id'.")
    if not isinstance(objects, list):
        raise SceneError("Object table requires an 'objects' list.")
    return frame_id, objects


def _numbers(values: Any, expected_count: int, description: str) -> List[float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise SceneError(f"{description} must be a list of {expected_count} numbers.")
    if len(values) != expected_count:
        raise SceneError(f"{description} must contain {expected_count} numbers, got {len(values)}.")
    try:
        return [float(value) for value in values]
    except (TypeError, ValueError) as error:
        raise SceneError(f"{description} must contain only numbers.") from error


def object_pose(entry: Dict[str, Any]) -> Pose:
    """Convert one object-table pose into a ROS pose message."""
    try:
        position = _numbers(entry["pose"]["position"], 3, f"{entry['id']}.pose.position")
        quaternion = _numbers(entry["pose"]["quat_xyzw"], 4, f"{entry['id']}.pose.quat_xyzw")
    except (KeyError, TypeError) as error:
        raise SceneError(f"Malformed pose for object: {entry!r}") from error

    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = position
    pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w = quaternion
    return pose


def _box_primitive(dimensions: Sequence[float]) -> SolidPrimitive:
    primitive = SolidPrimitive()
    primitive.type = SolidPrimitive.BOX
    primitive.dimensions = list(dimensions)
    return primitive


def _box_dimensions(entry: Dict[str, Any]) -> List[float]:
    """Read box dimensions, retaining a default for older object tables."""
    object_id = entry.get("id", "<unknown>")
    size = entry.get("size")
    if size is None and entry.get("type") == "table":
        size = DEFAULT_TABLE_SIZE
    dimensions = _numbers(size, 3, f"{object_id}.size")
    if any(value <= 0.0 for value in dimensions):
        raise SceneError(f"{object_id}.size values must all be positive.")
    return dimensions


def _open_container_geometry(entry: Dict[str, Any]) -> Tuple[List[SolidPrimitive], List[Pose]]:
    """Build a bottom and four walls for an axis-aligned open container."""
    object_id = entry.get("id", "<unknown>")
    outer_x, outer_y, outer_z = _box_dimensions(entry)
    geometry = entry.get("scene_geometry", {})
    try:
        wall = float(geometry["wall_thickness"])
        bottom = float(geometry["bottom_thickness"])
    except (KeyError, TypeError, ValueError) as error:
        raise SceneError(
            f"{object_id}.scene_geometry needs numeric wall_thickness and bottom_thickness."
        ) from error
    if wall <= 0.0 or bottom <= 0.0:
        raise SceneError(f"{object_id} wall and bottom thickness must be positive.")
    if 2.0 * wall >= outer_x or 2.0 * wall >= outer_y or bottom >= outer_z:
        raise SceneError(f"{object_id} container wall or bottom thickness is too large.")

    container_pose = object_pose(entry)
    quaternion = container_pose.orientation
    if any(abs(value) > 1e-6 for value in (quaternion.x, quaternion.y, quaternion.z)) or abs(
        quaternion.w - 1.0
    ) > 1e-6:
        raise SceneError(f"{object_id} open containers currently require identity orientation.")

    def pose_at(dx: float, dy: float, dz: float) -> Pose:
        pose = Pose()
        pose.position.x = container_pose.position.x + dx
        pose.position.y = container_pose.position.y + dy
        pose.position.z = container_pose.position.z + dz
        pose.orientation = container_pose.orientation
        return pose

    wall_height = outer_z - bottom
    bottom_center_z = -outer_z / 2.0 + bottom / 2.0
    wall_center_z = bottom_center_z + bottom / 2.0 + wall_height / 2.0
    inner_x = outer_x - 2.0 * wall
    inner_y = outer_y - 2.0 * wall

    primitives = [
        _box_primitive([outer_x, outer_y, bottom]),
        _box_primitive([wall, outer_y, wall_height]),
        _box_primitive([wall, outer_y, wall_height]),
        _box_primitive([inner_x, wall, wall_height]),
        _box_primitive([inner_x, wall, wall_height]),
    ]
    poses = [
        pose_at(0.0, 0.0, bottom_center_z),
        pose_at(-outer_x / 2.0 + wall / 2.0, 0.0, wall_center_z),
        pose_at(outer_x / 2.0 - wall / 2.0, 0.0, wall_center_z),
        pose_at(0.0, -outer_y / 2.0 + wall / 2.0, wall_center_z),
        pose_at(0.0, outer_y / 2.0 - wall / 2.0, wall_center_z),
    ]
    return primitives, poses


def object_geometry(entry: Dict[str, Any]) -> Tuple[List[SolidPrimitive], List[Pose]]:
    """Map project object types to one or more MoveIt collision primitives."""
    object_id = entry.get("id", "<unknown>")
    object_type = entry.get("type")

    if object_type in {"cube", "box", "table"}:
        if entry.get("scene_geometry", {}).get("kind") == "open_container":
            return _open_container_geometry(entry)
        return [_box_primitive(_box_dimensions(entry))], [object_pose(entry)]

    if object_type == "cylinder":
        try:
            size = entry["size"]
            radius = float(size["radius"])
            height = float(size["height"])
        except (KeyError, TypeError, ValueError) as error:
            raise SceneError(
                f"{object_id}.size for a cylinder needs numeric 'radius' and 'height'."
            ) from error
        if radius <= 0.0 or height <= 0.0:
            raise SceneError(f"{object_id} cylinder radius and height must be positive.")
        primitive = SolidPrimitive()
        primitive.type = SolidPrimitive.CYLINDER
        primitive.dimensions = [height, radius]
        return [primitive], [object_pose(entry)]

    raise SceneError(f"Unsupported object type '{object_type}' for {object_id}.")


def collision_object(
    entry: Dict[str, Any],
    frame_id: str,
    *,
    pose_override: Pose | None = None,
) -> CollisionObject:
    """Build an ADD operation for one static scene object."""
    object_id = entry.get("id")
    if not isinstance(object_id, str) or not object_id:
        raise SceneError(f"Object entry needs a non-empty string id: {entry!r}")

    message = CollisionObject()
    message.id = object_id
    message.header.frame_id = frame_id
    message.operation = CollisionObject.ADD
    primitives, primitive_poses = object_geometry(entry)
    if pose_override is not None:
        if len(primitive_poses) != 1:
            raise SceneError(
                f"Cannot place multi-primitive object '{object_id}' with one pose override."
            )
        primitive_poses = [pose_override]
    message.primitives.extend(primitives)
    message.primitive_poses.extend(primitive_poses)
    return message


def object_color(entry: Dict[str, Any]) -> ObjectColor:
    """Choose a visible RViz color from the existing semantic color label."""
    rgba = COLOR_BY_NAME.get(entry.get("color"), (0.95, 0.75, 0.1, 1.0))
    color = ObjectColor()
    color.id = entry["id"]
    color.color = ColorRGBA(r=rgba[0], g=rgba[1], b=rgba[2], a=rgba[3])
    return color


def scene_request(objects: Iterable[Dict[str, Any]], frame_id: str, *, remove: bool) -> PlanningScene:
    """Create a PlanningScene diff that adds or removes all listed objects."""
    scene = PlanningScene()
    scene.is_diff = True

    for entry in objects:
        if remove:
            object_id = entry.get("id")
            if not isinstance(object_id, str) or not object_id:
                raise SceneError(f"Object entry needs a non-empty string id: {entry!r}")
            message = CollisionObject()
            message.id = object_id
            message.header.frame_id = frame_id
            message.operation = CollisionObject.REMOVE
        else:
            message = collision_object(entry, frame_id)
            scene.object_colors.append(object_color(entry))
        scene.world.collision_objects.append(message)
    return scene


def managed_scene_state(node: Node, service_name: str) -> Tuple[List[AttachedCollisionObject], set[str]]:
    """Read existing managed-object state before applying a clear or reset diff."""
    scene = get_planning_scene(
        node,
        service_name,
        (
            PlanningSceneComponents.ROBOT_STATE_ATTACHED_OBJECTS
            | PlanningSceneComponents.WORLD_OBJECT_GEOMETRY
        ),
    )
    attachments = list(scene.robot_state.attached_collision_objects)
    world_object_ids = {
        collision_object.id
        for collision_object in scene.world.collision_objects
        if collision_object.id
    }
    return attachments, world_object_ids


def get_planning_scene(node: Node, service_name: str, components: int) -> PlanningScene:
    """Synchronously query exactly the Planning Scene components needed by a command."""
    client = node.create_client(GetPlanningScene, service_name)
    node.get_logger().info(f"Waiting for Planning Scene query service: {service_name}")
    while not client.wait_for_service(timeout_sec=1.0):
        node.get_logger().info("Planning Scene query service not available yet; waiting...")

    request = GetPlanningScene.Request()
    request.components.components = components
    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future)
    response = future.result()
    if response is None:
        raise RuntimeError("/get_planning_scene returned no response.")
    return response.scene


def grasp_links(gripper_link: str) -> List[str]:
    return PANDA_HAND_TOUCH_LINKS if gripper_link == "panda_hand" else [gripper_link]


def _ensure_acm_name(names: List[str], entries: List[AllowedCollisionEntry], name: str) -> int:
    if name in names:
        return names.index(name)
    names.append(name)
    for entry in entries:
        entry.enabled.append(False)
    new_entry = AllowedCollisionEntry()
    new_entry.enabled = [False] * len(names)
    entries.append(new_entry)
    return len(names) - 1


def grasp_collision_request(
    current_scene: PlanningScene,
    object_id: str,
    gripper_link: str,
    *,
    allowed: bool,
) -> PlanningScene:
    """Enable or disable collision only between one grasp target and gripper links."""
    acm = current_scene.allowed_collision_matrix
    names = list(acm.entry_names)
    entries = list(acm.entry_values)
    object_index = _ensure_acm_name(names, entries, object_id)

    for link_name in grasp_links(gripper_link):
        link_index = _ensure_acm_name(names, entries, link_name)
        entries[object_index].enabled[link_index] = allowed
        entries[link_index].enabled[object_index] = allowed

    acm.entry_names = names
    acm.entry_values = entries
    scene = PlanningScene()
    scene.is_diff = True
    scene.allowed_collision_matrix = acm
    return scene


def clear_request(
    objects: Iterable[Dict[str, Any]],
    frame_id: str,
    current_attachments: Iterable[AttachedCollisionObject],
    current_world_object_ids: set[str],
) -> PlanningScene:
    """Remove only existing managed objects and matching attached state.

    MoveIt treats a REMOVE request for an unknown object as a rejected planning
    scene update. Filtering first makes ``--reset`` idempotent on a newly
    started demo as well as after a previous run.
    """
    all_object_ids = {entry.get("id") for entry in objects}
    entries = [entry for entry in objects if entry.get("id") in current_world_object_ids]
    scene = scene_request(entries, frame_id, remove=True)
    scene.robot_state.is_diff = True

    for attachment in current_attachments:
        if attachment.object.id not in all_object_ids:
            continue
        detach = AttachedCollisionObject()
        detach.link_name = attachment.link_name
        detach.object.id = attachment.object.id
        detach.object.operation = CollisionObject.REMOVE
        scene.robot_state.attached_collision_objects.append(detach)
    return scene


def find_object(objects: Iterable[Dict[str, Any]], object_id: str) -> Dict[str, Any]:
    """Return one object-table entry by its stable scene ID."""
    for entry in objects:
        if entry.get("id") == object_id:
            return entry
    raise SceneError(f"Object '{object_id}' was not found in the object table.")


def pose_from_values(position: Sequence[float], quat_xyzw: Sequence[float]) -> Pose:
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = _numbers(position, 3, "position")
    quaternion = _numbers(quat_xyzw, 4, "quat_xyzw")
    pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w = quaternion
    return pose


def _quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    return Quaternion(
        x=left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y,
        y=left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x,
        z=left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w,
        w=left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z,
    )


def _quaternion_inverse(quaternion: Quaternion) -> Quaternion:
    norm_squared = (
        quaternion.x * quaternion.x
        + quaternion.y * quaternion.y
        + quaternion.z * quaternion.z
        + quaternion.w * quaternion.w
    )
    if norm_squared == 0.0:
        raise SceneError("Cannot transform a pose using a zero-length quaternion.")
    return Quaternion(
        x=-quaternion.x / norm_squared,
        y=-quaternion.y / norm_squared,
        z=-quaternion.z / norm_squared,
        w=quaternion.w / norm_squared,
    )


def _rotate_vector(quaternion: Quaternion, vector: Sequence[float]) -> Tuple[float, float, float]:
    vector_quaternion = Quaternion(x=vector[0], y=vector[1], z=vector[2], w=0.0)
    rotated = _quaternion_multiply(
        _quaternion_multiply(quaternion, vector_quaternion),
        _quaternion_inverse(quaternion),
    )
    return rotated.x, rotated.y, rotated.z


def pose_in_link_frame(world_pose: Pose, world_from_link: Any) -> Pose:
    """Express a world-frame pose relative to the current gripper-link frame."""
    translation = world_from_link.transform.translation
    link_orientation = world_from_link.transform.rotation
    inverse_orientation = _quaternion_inverse(link_orientation)
    relative_position = _rotate_vector(
        inverse_orientation,
        (
            world_pose.position.x - translation.x,
            world_pose.position.y - translation.y,
            world_pose.position.z - translation.z,
        ),
    )
    relative_orientation = _quaternion_multiply(inverse_orientation, world_pose.orientation)

    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = relative_position
    pose.orientation = relative_orientation
    return pose


def lookup_world_from_link(
    node: Node,
    world_frame: str,
    link_name: str,
    timeout_seconds: float,
) -> Any:
    """Wait briefly for TF, then return the current world-to-link transform."""
    buffer = Buffer()
    listener = TransformListener(buffer, node, spin_thread=False)
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            return buffer.lookup_transform(world_frame, link_name, Time())
        except TransformException as error:
            last_error = error
            rclpy.spin_once(node, timeout_sec=0.1)

    del listener
    raise RuntimeError(
        f"Could not get TF transform '{world_frame}' <- '{link_name}' within "
        f"{timeout_seconds:.1f}s: {last_error}"
    )


def attach_request(
    node: Node,
    entry: Dict[str, Any],
    world_frame: str,
    gripper_link: str,
    transform_timeout: float,
) -> PlanningScene:
    """Attach an object without changing its world pose.

    An ``AttachedCollisionObject`` transfers the matching object out of MoveIt's
    world scene.  Do not send a second explicit REMOVE in the same diff: that
    duplicate removal is rejected by this MoveIt configuration.
    """
    world_from_link = lookup_world_from_link(
        node, world_frame, gripper_link, transform_timeout
    )
    relative_pose = pose_in_link_frame(object_pose(entry), world_from_link)
    attached_object = collision_object(entry, gripper_link, pose_override=relative_pose)

    attachment = AttachedCollisionObject()
    attachment.link_name = gripper_link
    attachment.object = attached_object
    attachment.touch_links = (
        PANDA_HAND_TOUCH_LINKS if gripper_link == "panda_hand" else [gripper_link]
    )

    scene = PlanningScene()
    scene.is_diff = True
    scene.robot_state.is_diff = True
    scene.robot_state.attached_collision_objects.append(attachment)
    scene.object_colors.append(object_color(entry))
    return scene


def place_request(
    entry: Dict[str, Any],
    world_frame: str,
    pose: Pose,
    gripper_link: str,
) -> PlanningScene:
    """Detach an object and restore it to the world at its final placement pose."""
    detach = AttachedCollisionObject()
    detach.link_name = gripper_link
    detach.object.id = entry["id"]
    detach.object.operation = CollisionObject.REMOVE

    scene = PlanningScene()
    scene.is_diff = True
    scene.robot_state.is_diff = True
    scene.robot_state.attached_collision_objects.append(detach)
    scene.world.collision_objects.append(
        collision_object(entry, world_frame, pose_override=pose)
    )
    scene.object_colors.append(object_color(entry))
    return scene


def apply_scene(node: Node, service_name: str, scene: PlanningScene) -> None:
    """Synchronously apply a planning-scene diff through move_group."""
    client = node.create_client(ApplyPlanningScene, service_name)
    node.get_logger().info(f"Waiting for Planning Scene service: {service_name}")
    while not client.wait_for_service(timeout_sec=1.0):
        node.get_logger().info("Planning Scene service not available yet; waiting...")

    request = ApplyPlanningScene.Request()
    request.scene = scene
    future = client.call_async(request)
    rclpy.spin_until_future_complete(node, future)

    response = future.result()
    if response is None:
        raise RuntimeError("/apply_planning_scene returned no response.")
    if not response.success:
        raise RuntimeError("move_group rejected the Planning Scene update.")


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Load configs/objects.json into MoveIt and show it in RViz."
    )
    parser.add_argument(
        "--objects",
        default=project_root / "configs" / "objects.json",
        help="Path to the shared scene object table.",
    )
    parser.add_argument(
        "--frame-id",
        help="Override the top-level frame_id from the object table.",
    )
    parser.add_argument(
        "--service",
        default="/apply_planning_scene",
        help="MoveIt ApplyPlanningScene service name.",
    )
    parser.add_argument(
        "--get-service",
        default="/get_planning_scene",
        help="MoveIt GetPlanningScene service used by --clear and --reset.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--clear",
        action="store_true",
        help="Remove configured world objects and matching attached object state.",
    )
    mode.add_argument(
        "--reset",
        action="store_true",
        help="Clear managed scene state, then restore the initial objects.json scene.",
    )
    mode.add_argument(
        "--attach",
        metavar="OBJECT_ID",
        help="Attach one object-table object to the current gripper pose.",
    )
    mode.add_argument(
        "--place",
        metavar="OBJECT_ID",
        help="Detach one object and add it back to the world at --position.",
    )
    mode.add_argument(
        "--allow-grasp-collision",
        metavar="OBJECT_ID",
        help="Allow collision between one grasp target and the configured gripper links.",
    )
    mode.add_argument(
        "--disallow-grasp-collision",
        metavar="OBJECT_ID",
        help="Restore collision checking between one target and the configured gripper links.",
    )
    parser.add_argument(
        "--gripper-link",
        default="panda_hand",
        help="Link used for --attach. Defaults to Panda's grasp link panda_hand.",
    )
    parser.add_argument(
        "--position",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help="World-frame object center position required by --place.",
    )
    parser.add_argument(
        "--quat-xyzw",
        nargs=4,
        type=float,
        default=[0.0, 0.0, 0.0, 1.0],
        metavar=("X", "Y", "Z", "W"),
        help="World-frame orientation for --place.",
    )
    parser.add_argument(
        "--transform-timeout",
        type=float,
        default=3.0,
        help="Seconds to wait for the gripper TF transform during --attach.",
    )
    args = parser.parse_args()

    if args.place and args.position is None:
        parser.error("--place requires --position X Y Z.")
    if args.position is not None and not args.place:
        parser.error("--position may only be used together with --place.")
    if args.transform_timeout <= 0.0:
        parser.error("--transform-timeout must be positive.")

    table_frame_id, objects = load_objects(str(args.objects))
    frame_id = args.frame_id or table_frame_id

    rclpy.init()
    node = Node("scene_manager")
    try:
        if args.attach:
            entry = find_object(objects, args.attach)
            scene = attach_request(
                node,
                entry,
                frame_id,
                args.gripper_link,
                args.transform_timeout,
            )
            attachment = scene.robot_state.attached_collision_objects[0]
            relative_pose = attachment.object.primitive_poses[0]
            node.get_logger().info(
                f"Attach request: id={args.attach}, link={args.gripper_link}, "
                f"touch_links={list(attachment.touch_links)}, "
                f"relative_position=[{relative_pose.position.x:.3f}, "
                f"{relative_pose.position.y:.3f}, {relative_pose.position.z:.3f}]"
            )
            action = f"Attached {args.attach} to '{args.gripper_link}'"
        elif args.place:
            entry = find_object(objects, args.place)
            scene = place_request(
                entry,
                frame_id,
                pose_from_values(args.position, args.quat_xyzw),
                args.gripper_link,
            )
            action = f"Placed {args.place} at {list(args.position)}"
        elif args.allow_grasp_collision or args.disallow_grasp_collision:
            object_id = args.allow_grasp_collision or args.disallow_grasp_collision
            find_object(objects, object_id)
            current_scene = get_planning_scene(
                node, args.get_service, PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
            )
            allowed = args.allow_grasp_collision is not None
            scene = grasp_collision_request(
                current_scene, object_id, args.gripper_link, allowed=allowed
            )
            action = (
                f"Allowed grasp collision for {object_id}"
                if allowed
                else f"Restored collision checking for {object_id}"
            )
        elif args.clear or args.reset:
            current_attachments, current_world_object_ids = managed_scene_state(
                node, args.get_service
            )
            scene = clear_request(
                objects,
                frame_id,
                current_attachments,
                current_world_object_ids,
            )
            if scene.world.collision_objects or scene.robot_state.attached_collision_objects:
                apply_scene(node, args.service, scene)
            detached_count = len(scene.robot_state.attached_collision_objects)
            node.get_logger().info(
                f"Cleared {len(scene.world.collision_objects)} world objects and "
                f"{detached_count} attached objects."
            )
            if args.reset:
                scene = scene_request(objects, frame_id, remove=False)
                action = f"Reset {len(objects)} scene objects"
            else:
                return
        else:
            scene = scene_request(objects, frame_id, remove=False)
            action = "Added"
        apply_scene(node, args.service, scene)
        if args.reset:
            current_scene = get_planning_scene(
                node, args.get_service, PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
            )
            for entry in objects:
                if not entry.get("pickable", False):
                    continue
                reset_collision_scene = grasp_collision_request(
                    current_scene,
                    entry["id"],
                    args.gripper_link,
                    allowed=False,
                )
                apply_scene(node, args.service, reset_collision_scene)
                current_scene = get_planning_scene(
                    node, args.get_service, PlanningSceneComponents.ALLOWED_COLLISION_MATRIX
                )
        if (
            args.attach
            or args.place
            or args.allow_grasp_collision
            or args.disallow_grasp_collision
        ):
            node.get_logger().info(f"{action} in frame '{frame_id}'.")
        else:
            node.get_logger().info(
                f"{action} {len(objects)} scene objects in frame '{frame_id}'."
            )
        if not args.clear and not args.attach and not args.place and any(
            item.get("type") == "table" and item.get("size") is None for item in objects
        ):
            node.get_logger().warn(
                "Table has no size; using default [1.0, 0.8, 0.04]. "
                "Add an explicit size to configs/objects.json before final demos."
            )
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
