# 定义任务 DSL

定义中间语义表示：
```
{
  "intent": "pick_place",
  "target": {
    "type": "cube",
    "color": "red"
  },
  "destination": {
    "type": "box",
    "color": "blue"
  },
  "relation": "in"
}
```

保存成：
`
configs/task_schema.json `

同时定义对象表：
`
configs/objects.json `

对象至少包括：
```
red cube
blue cube
green cylinder
blue box
green box
table center
```

# 对象grounding初版
新增 [object_grounder.py](sandbox:/workspace/src/object_grounder.py)：按 `type`、`color` 匹配对象；目标必须 `pickable=true`，目标位置还会根据 DSL 的 `relation` 校验 `accepts`，例如 `blue box + in`。

更新 [arm_executor.py](sandbox:/workspace/src/arm_executor.py)：不再硬编码红色方块和蓝色盒子的 pose，而是先 grounding，再执行原有 pick-and-place 流程。另附现场演示用的 [demo_pick_place.json](sandbox:/workspace/configs/demo_pick_place.json)。

运行方式：

```bash
cd /workspace

# 单独演示 red cube -> red_cube_1
python3 src/object_grounder.py --target "red cube"

# DSL grounding + 完整 dry-run 抓取流程
python3 src/arm_executor.py \
  --task-file configs/demo_pick_place.json \
  --client-script src/panda_moveit_client.py
```

已验证输出包含：

```text
Instruction target: red cube
Grounded target: red_cube_1
Grounded pose: [0.45, 0.20, 0.04]
```

同时通过了 `in` / `on` 关系校验和“不可抓取对象不能作为 target”的检查。
