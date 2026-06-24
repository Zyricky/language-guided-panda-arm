"""Regression tests for Day-4 scene-aware instruction validation."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from validator import TaskValidator, validate_instruction


class TaskValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = TaskValidator(ROOT / "configs" / "objects.json")
        with (ROOT / "data" / "instructions.jsonl").open(encoding="utf-8") as dataset_file:
            cls.records = [json.loads(line) for line in dataset_file if line.strip()]

    def test_all_valid_dataset_commands_are_accepted(self) -> None:
        for record in (record for record in self.records if record["valid"]):
            with self.subTest(record_id=record["id"]):
                self.assertEqual(validate_instruction(record["instruction"], self.validator).as_dict(), {"valid": True})

    def test_all_invalid_dataset_commands_have_expected_reason(self) -> None:
        for record in (record for record in self.records if not record["valid"]):
            with self.subTest(record_id=record["id"]):
                self.assertEqual(
                    validate_instruction(record["instruction"], self.validator).as_dict(),
                    {"valid": False, "reason": record["expected_reason"]},
                )

    def test_destination_capability_is_checked_for_container_relations(self) -> None:
        result = self.validator.validate(
            {
                "intent": "pick_place",
                "target": {"type": "cube", "color": "red"},
                "destination": {"type": "table", "color": None},
                "relation": "in",
            }
        )
        self.assertEqual(result.as_dict(), {"valid": False, "reason": "destination does not support relation"})

    def test_ambiguous_target_is_rejected(self) -> None:
        result = validate_instruction("把方块放进蓝色盒子里", self.validator)
        self.assertEqual(result.as_dict(), {"valid": False, "reason": "ambiguous target"})


if __name__ == "__main__":
    unittest.main()
