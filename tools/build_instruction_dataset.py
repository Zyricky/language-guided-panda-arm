#!/usr/bin/env python3
"""Build the fixed Day-3 Chinese manipulation-instruction dataset.

The generated JSONL intentionally contains both syntactically parseable but
scene-invalid commands and unparseable ambiguous commands.  This separation
lets Day 4 evaluate parser behavior and validator behavior independently.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "instructions.jsonl"

ObjectSpec = Tuple[str, Dict[str, Optional[str]]]

TARGETS: List[ObjectSpec] = [
    ("红色方块", {"type": "cube", "color": "red"}),
    ("蓝色方块", {"type": "cube", "color": "blue"}),
    ("绿色圆柱", {"type": "cylinder", "color": "green"}),
]
BOXES: List[ObjectSpec] = [
    ("蓝色盒子", {"type": "box", "color": "blue"}),
    ("绿色盒子", {"type": "box", "color": "green"}),
]
TABLE: ObjectSpec = ("桌子", {"type": "table", "color": None})


def _pick_dsl(target: Dict[str, Optional[str]]) -> Dict[str, object]:
    return {"intent": "pick", "target": target}


def _place_dsl(
    target: Dict[str, Optional[str]],
    destination: Dict[str, Optional[str]],
    relation: str,
) -> Dict[str, object]:
    return {
        "intent": "pick_place",
        "target": target,
        "destination": destination,
        "relation": relation,
    }


def _valid_record(category: str, instruction: str, gold: Dict[str, object]) -> Dict[str, object]:
    return {
        "category": category,
        "instruction": instruction,
        "gold": gold,
        "valid": True,
    }


def _invalid_record(category: str, instruction: str, reason: str) -> Dict[str, object]:
    return {
        "category": category,
        "instruction": instruction,
        "gold": None,
        "valid": False,
        "expected_reason": reason,
    }


def _template_records() -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    in_templates = [
        "把{target}放进{destination}",
        "把{target}放进{destination}里",
        "将{target}放到{destination}里面",
        "请将{target}移动到{destination}里",
    ]
    for target_text, target in TARGETS:
        for destination_text, destination in BOXES:
            for template in in_templates:
                records.append(
                    _valid_record(
                        "template",
                        template.format(target=target_text, destination=destination_text),
                        _place_dsl(target, destination, "in"),
                    )
                )

    pick_templates = ["拿起{target}", "请拿起{target}", "把{target}拿起", "将{target}拿起"]
    for target_text, target in TARGETS:
        for template in pick_templates:
            records.append(_valid_record("template", template.format(target=target_text), _pick_dsl(target)))

    for instruction, target in [
        ("把红色方块放到桌子中央", TARGETS[0][1]),
        ("将蓝色方块移动到桌子中央", TARGETS[1][1]),
        ("请把绿色圆柱放到桌子中央", TARGETS[2][1]),
        ("请将红色方块移动到桌子中央", TARGETS[0][1]),
    ]:
        records.append(_valid_record("template", instruction, _place_dsl(target, TABLE[1], "center")))

    assert len(records) == 40
    return records


def _paraphrase_records() -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    target_aliases = [
        ("红积木", TARGETS[0][1]),
        ("蓝积木", TARGETS[1][1]),
        ("绿圆柱", TARGETS[2][1]),
    ]
    destination_aliases = [("蓝容器", BOXES[0][1]), ("绿容器", BOXES[1][1])]
    templates = [
        "把{target}放进{destination}",
        "请把{target}放进{destination}里面",
        "将{target}挪到{destination}里",
        "请将{target}移动到{destination}里面",
        "把{target}放到{destination}里",
        "请把{target}挪到{destination}里面",
        "将{target}放进{destination}里",
        "请将{target}挪到{destination}里",
    ]
    for target_text, target in target_aliases:
        for destination_text, destination in destination_aliases:
            for template in templates:
                records.append(
                    _valid_record(
                        "paraphrase",
                        template.format(target=target_text, destination=destination_text),
                        _place_dsl(target, destination, "in"),
                    )
                )

    records.extend(
        [
            _valid_record("paraphrase", "抓起红积木", _pick_dsl(TARGETS[0][1])),
            _valid_record("paraphrase", "请取蓝块", _pick_dsl(TARGETS[1][1])),
        ]
    )
    assert len(records) == 50
    return records


def _spatial_records() -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    target_aliases = [
        ("红色方块", TARGETS[0][1]),
        ("蓝块", TARGETS[1][1]),
        ("绿色圆柱", TARGETS[2][1]),
    ]
    destination_aliases = [("蓝色盒子", BOXES[0][1]), ("绿容器", BOXES[1][1])]

    relation_templates = {
        "near": ["把{target}放到{destination}旁边", "请将{target}移动到{destination}旁边"],
        "left_of": ["将{target}挪到{destination}左边", "请把{target}放到{destination}左边"],
        "right_of": ["把{target}放到{destination}右边", "请将{target}移动到{destination}右边"],
    }
    relation_counts = {"near": 10, "left_of": 10, "right_of": 6}
    for relation, expected_count in relation_counts.items():
        candidates = []
        for target_text, target in target_aliases:
            for destination_text, destination in destination_aliases:
                for template in relation_templates[relation]:
                    candidates.append(
                        _valid_record(
                            "spatial_relation",
                            template.format(target=target_text, destination=destination_text),
                            _place_dsl(target, destination, relation),
                        )
                    )
        records.extend(candidates[:expected_count])

    for instruction, target in [
        ("把红积木放到桌子中央", TARGETS[0][1]),
        ("请将蓝块移动到桌子中央", TARGETS[1][1]),
        ("把绿色圆柱挪到桌子中央", TARGETS[2][1]),
        ("请把红色方块移动到桌子中央", TARGETS[0][1]),
    ]:
        records.append(_valid_record("spatial_relation", instruction, _place_dsl(target, TABLE[1], "center")))

    assert len(records) == 30
    return records


def _invalid_records() -> List[Dict[str, object]]:
    cases = [
        ("拿起方块", "ambiguous target"),
        ("请抓起积木", "ambiguous target"),
        ("把方块放进蓝色盒子里", "ambiguous target"),
        ("将积木移动到绿色盒子旁边", "ambiguous target"),
        ("把块放到蓝容器左边", "ambiguous target"),
        ("请把方块挪到绿容器右边", "ambiguous target"),
        ("把红色方块放进盒子里", "ambiguous destination"),
        ("将蓝色方块移动到盒子旁边", "ambiguous destination"),
        ("把绿色圆柱放到盒子左边", "ambiguous destination"),
        ("请把红积木挪到容器右边", "ambiguous destination"),
        ("把蓝色方块放进容器里面", "ambiguous destination"),
        ("将绿色圆柱移动到盒子旁边", "ambiguous destination"),
        ("拿起红色圆柱", "target not found"),
        ("把绿色方块放进蓝色盒子里", "target not found"),
        ("将蓝色圆柱移动到绿色盒子旁边", "target not found"),
        ("把红色圆柱放到桌子中央", "target not found"),
        ("请抓起绿色积木", "target not found"),
        ("把红色方块放进红色盒子里", "destination not found"),
        ("将蓝色方块移动到红色盒子旁边", "destination not found"),
        ("把绿色圆柱放到绿色桌子中央", "destination not found"),
        ("请把红积木挪到红容器里", "destination not found"),
        ("把红色方块放到红色方块旁边", "same target and destination"),
        ("将蓝色方块移动到蓝色方块左边", "same target and destination"),
        ("把绿色圆柱放到绿色圆柱右边", "same target and destination"),
        ("把红色方块放到蓝色盒子上面", "unsupported relation"),
        ("将蓝积木移动到绿容器后面", "unsupported relation"),
        ("放进蓝色盒子里", "missing target"),
        ("把红色方块放进里", "missing destination"),
        ("移动到绿色盒子旁边", "missing target"),
        ("把蓝色方块挪到旁边", "missing destination"),
    ]
    records = [_invalid_record("invalid_or_ambiguous", instruction, reason) for instruction, reason in cases]
    assert len(records) == 30
    return records


def build_records() -> List[Dict[str, object]]:
    """Return the 150 deterministic Day-3 dataset records with stable IDs."""
    records = _template_records() + _paraphrase_records() + _spatial_records() + _invalid_records()
    assert len(records) == 150
    for index, record in enumerate(records, start=1):
        record["id"] = f"instruction_{index:03d}"
    return records


def main() -> None:
    records = build_records()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote {len(records)} records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
