"""Integrity checks for the fixed Day-3 instruction dataset."""

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nl_parser import parse_instruction


DATASET_PATH = ROOT / "data" / "instructions.jsonl"


class InstructionDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with DATASET_PATH.open(encoding="utf-8") as dataset_file:
            cls.records = [json.loads(line) for line in dataset_file if line.strip()]

    def test_expected_size_and_category_counts(self) -> None:
        self.assertEqual(len(self.records), 150)
        self.assertEqual(
            Counter(record["category"] for record in self.records),
            {
                "template": 40,
                "paraphrase": 50,
                "spatial_relation": 30,
                "invalid_or_ambiguous": 30,
            },
        )

    def test_record_ids_are_unique(self) -> None:
        ids = [record["id"] for record in self.records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_valid_records_have_gold_dsl_accepted_by_parser(self) -> None:
        valid_records = [record for record in self.records if record["valid"]]
        self.assertEqual(len(valid_records), 120)
        for record in valid_records:
            with self.subTest(record_id=record["id"]):
                self.assertEqual(parse_instruction(record["instruction"]), record["gold"])

    def test_invalid_records_reserve_a_validator_reason(self) -> None:
        invalid_records = [record for record in self.records if not record["valid"]]
        self.assertEqual(len(invalid_records), 30)
        for record in invalid_records:
            with self.subTest(record_id=record["id"]):
                self.assertIsNone(record["gold"])
                self.assertTrue(record["expected_reason"])


if __name__ == "__main__":
    unittest.main()
