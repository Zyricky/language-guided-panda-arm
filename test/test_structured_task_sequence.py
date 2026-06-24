"""Regression tests for single-task and multi-task JSON compatibility."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from arm_executor import ExecutionError, prepare_structured_tasks
from skill_planner import load_task, load_tasks


class StructuredTaskSequenceTest(unittest.TestCase):
    objects_path = ROOT / "configs" / "objects.json"
    sequence_path = ROOT / "configs" / "demo_pick_place.json"

    def test_load_tasks_accepts_the_demo_sequence_format(self) -> None:
        tasks = load_tasks(str(self.sequence_path))
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["id"], "put_red_in_blue")
        self.assertEqual(tasks[1]["id"], "put_blue_in_green")

    def test_load_task_keeps_single_task_api(self) -> None:
        task = load_task(None)
        self.assertEqual(task["intent"], "pick_place")
        with self.assertRaisesRegex(ValueError, "contains multiple tasks"):
            load_task(str(self.sequence_path))

    def test_prepares_demo_sequence_in_order(self) -> None:
        prepared_tasks = prepare_structured_tasks(load_tasks(str(self.sequence_path)), self.objects_path)
        self.assertEqual(
            [prepared.grounded["target"].object_id for prepared in prepared_tasks],
            ["red_cube_1", "blue_cube_1"],
        )
        self.assertEqual(prepared_tasks[0].plan[0].name, "MoveToHome")
        self.assertEqual(prepared_tasks[1].plan[-1].name, "ReturnHome")

    def test_rejects_repeated_target_before_execution(self) -> None:
        tasks = [
            {
                "intent": "pick_place",
                "target": {"id": "red_cube_1"},
                "destination": {"id": "blue_box_1"},
                "relation": "in",
            },
            {
                "intent": "pick_place",
                "target": {"id": "red_cube_1"},
                "destination": {"id": "green_box_1"},
                "relation": "in",
            },
        ]
        with self.assertRaisesRegex(ExecutionError, "reuses target 'red_cube_1'"):
            prepare_structured_tasks(tasks, self.objects_path)


if __name__ == "__main__":
    unittest.main()
