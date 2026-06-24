"""Tests for the Day-7 natural-language-to-arm entry point."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from run_nl_task import NLTaskError, execute_prepared_tasks, prepare_nl_task, prepare_nl_tasks


class RunNLTaskTest(unittest.TestCase):
    objects_path = ROOT / "configs" / "objects.json"

    def test_prepares_executable_alias_rich_instruction(self) -> None:
        prepared = prepare_nl_task("请把红色积木放到蓝色盒子里面", self.objects_path)
        self.assertEqual(prepared.task["relation"], "in")
        self.assertEqual(prepared.grounded["target"].object_id, "red_cube_1")
        self.assertEqual(prepared.grounded["destination"].object_id, "blue_box_1")
        self.assertEqual(prepared.plan[0].name, "MoveToHome")
        self.assertEqual(prepared.plan[-1].name, "ReturnHome")

    def test_rejects_parse_failure_before_grounding(self) -> None:
        with self.assertRaisesRegex(NLTaskError, "Unsupported instruction") as raised:
            prepare_nl_task("随便拿一个东西", self.objects_path)
        self.assertEqual(raised.exception.stage, "Parse error")

    def test_rejects_missing_scene_object(self) -> None:
        with self.assertRaisesRegex(NLTaskError, "target not found") as raised:
            prepare_nl_task("把红色圆柱放进蓝色盒子里", self.objects_path)
        self.assertEqual(raised.exception.stage, "Validation failed")

    def test_stops_valid_but_not_executable_relation(self) -> None:
        with self.assertRaisesRegex(NLTaskError, "only pick_place") as raised:
            prepare_nl_task("把蓝色方块放到绿色盒子旁边", self.objects_path)
        self.assertEqual(raised.exception.stage, "Execution not supported")

    def test_prepares_distinct_targets_in_input_order(self) -> None:
        prepared_tasks = prepare_nl_tasks(
            [
                "把红色方块放进蓝色盒子里",
                "把蓝色方块放进绿色盒子里",
            ],
            self.objects_path,
        )
        self.assertEqual(
            [prepared.grounded["target"].object_id for prepared in prepared_tasks],
            ["red_cube_1", "blue_cube_1"],
        )

    def test_rejects_reusing_a_target_before_execution(self) -> None:
        with self.assertRaisesRegex(NLTaskError, "reuses target 'red_cube_1'") as raised:
            prepare_nl_tasks(
                [
                    "把红色方块放进蓝色盒子里",
                    "把红色积木放进绿色容器里",
                ],
                self.objects_path,
            )
        self.assertEqual(raised.exception.stage, "Sequence validation failed")

    @patch("run_nl_task.ArmExecutor")
    def test_sequence_resets_once_and_executes_each_plan(self, executor_class) -> None:
        prepared_tasks = prepare_nl_tasks(
            [
                "把红色方块放进蓝色盒子里",
                "把蓝色方块放进绿色盒子里",
            ],
            self.objects_path,
        )
        executor = executor_class.return_value
        executor.execute_skill_plan.return_value = True

        result = execute_prepared_tasks(
            prepared_tasks,
            execute=False,
            reset_scene=True,
            objects_path=str(self.objects_path),
            client_script=str(ROOT / "src" / "panda_moveit_client.py"),
            scene_manager_script=str(ROOT / "src" / "scene_manager.py"),
            manipulation_params_path=str(ROOT / "configs" / "manipulation_params.json"),
            gripper_link=None,
        )

        self.assertTrue(result)
        executor.reset_scene.assert_called_once_with()
        self.assertEqual(executor.execute_skill_plan.call_count, 2)


if __name__ == "__main__":
    unittest.main()
