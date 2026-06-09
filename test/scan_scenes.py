"""
本脚本用于：
1. 固定测试 5 个 AI2-THOR 场景
2. 在每个场景中扫描并记录指定类别的物体
"""

import ai2thor.controller
import time

# 1. 定义测试场景和关注物体
# 固定使用的 5 个测试场景（厨房 / 客厅）
SCENES = [
    "FloorPlan1",
    "FloorPlan2",
    "FloorPlan3",
    "FloorPlan201",
    "FloorPlan202",
]

# 物体类别
TARGET_OBJECTS = {
    "Mug",
    "Cup",
    "Apple",
    "Tomato",
    "Bowl",
    "Plate",
    "Table",
    "CounterTop",
    "Sink",
    "Cabinet",
    "Fridge",
}


# 2. 初始化控制器（只初始化一次）
controller = ai2thor.controller.Controller(
    agentMode="default",   # 默认智能体模式
    gridSize=0.25,          # 移动步长
    quality="Low",          # 降低画质，加快扫描速度
    fullscreen=True
)

# 3. 遍历场景并扫描物体
for scene in SCENES:
    print(f"\n📌 当前场景: {scene}")

    # 切换到目标场景
    controller.reset(scene=scene)
    time.sleep(1.0)

    # 获取当前场景的所有物体信息
    objects = controller.last_event.metadata["objects"]
    time.sleep(1.0)

    found_objects = set()

    for obj in objects:
        obj_type = obj["objectType"]

                # 只记录我们关心的物体
        if obj_type in TARGET_OBJECTS:
            found_objects.add(obj_type)

        # 按字母顺序输出，方便阅读和写报告
    print("✅ 可用物体：")
    for obj in sorted(found_objects):
        print(f"  - {obj}")

    time.sleep(1.0)

# 4. 清理资源
controller.stop()
print("\n🎉 所有场景扫描完成！")



