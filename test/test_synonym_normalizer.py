"""Regression tests for Day-2 synonym normalization."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl_parser import parse_instruction
from synonym_normalizer import normalize_instruction


class SynonymNormalizerTest(unittest.TestCase):
    def test_normalizes_overlapping_color_and_type_aliases(self) -> None:
        self.assertEqual(normalize_instruction("把红积木放进蓝容器里面"), "把红色方块放进蓝色盒子里")

    def test_normalizes_pick_action(self) -> None:
        self.assertEqual(normalize_instruction("请抓起绿块"), "请拿起绿色方块")

    def test_normalizes_move_action(self) -> None:
        self.assertEqual(normalize_instruction("将蓝积木挪到绿容器旁边"), "将蓝色方块移动到绿色盒子旁边")

    def test_parser_accepts_alias_rich_command(self) -> None:
        self.assertEqual(
            parse_instruction("请把红积木挪到蓝容器里面"),
            {
                "intent": "pick_place",
                "target": {"type": "cube", "color": "red"},
                "destination": {"type": "box", "color": "blue"},
                "relation": "in",
            },
        )

    def test_parser_supports_left_and_right_relations(self) -> None:
        dsl = parse_instruction("把蓝块放到绿容器左边")
        self.assertEqual(dsl["relation"], "left_of")


if __name__ == "__main__":
    unittest.main()
