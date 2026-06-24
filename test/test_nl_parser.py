"""Focused regression tests for the Day-1 Chinese rule parser.
测试：
    python3 -m unittest discover -s test -t . -p "test_nl_parser.py" -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nl_parser import ParseError, parse_instruction


class RuleParserTest(unittest.TestCase):
    def test_pick_instruction(self) -> None:
        self.assertEqual(
            parse_instruction("拿起红色方块"),
            {"intent": "pick", "target": {"type": "cube", "color": "red"}},
        )

    def test_place_into_box(self) -> None:
        self.assertEqual(
            parse_instruction("把红色方块放进蓝色盒子里"),
            {
                "intent": "pick_place",
                "target": {"type": "cube", "color": "red"},
                "destination": {"type": "box", "color": "blue"},
                "relation": "in",
            },
        )

    def test_place_near_box(self) -> None:
        self.assertEqual(
            parse_instruction("将蓝色方块移动到绿色盒子旁边"),
            {
                "intent": "pick_place",
                "target": {"type": "cube", "color": "blue"},
                "destination": {"type": "box", "color": "green"},
                "relation": "near",
            },
        )

    def test_place_at_table_center(self) -> None:
        self.assertEqual(
            parse_instruction("把红色圆柱放到桌子中央。"),
            {
                "intent": "pick_place",
                "target": {"type": "cylinder", "color": "red"},
                "destination": {"type": "table", "color": None},
                "relation": "center",
            },
        )

    def test_reject_missing_relation(self) -> None:
        with self.assertRaises(ParseError):
            parse_instruction("把红色方块放到蓝色盒子")


if __name__ == "__main__":
    unittest.main()
