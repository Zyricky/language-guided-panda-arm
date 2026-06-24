import ai2thor.controller
import time
import numpy as np
from PIL import Image

# 1.初始化控制器 FloorPlan场景
controller = ai2thor.controller.Controller(
    agentMode = "default",
    scene = "FloorPlan1_physics",
    gridSize = 0.25,
    quality = "Medium",
    fullscreen=True,    # 开启全屏画面
)

print("✅ AI2-THOR Scene loading success!")

# 2.让智能体移动，验证物理引擎和动作交互
# event = controller.step(action = "MoveAhead")
# print(f"✅ agent move ahead success, cur_position:{event.metadata['agent']['position']}")

def step_and_wait(action, wait=3.0):
    event = controller.step(action = action)
    print(f"✅ 执行动作: {action}, 当前位置: {event.metadata['agent']['position']}")
    time.sleep(wait)
    return event

step_and_wait("MoveAhead", 3)
step_and_wait("RotateRight", 3)
step_and_wait("MoveAhead", 3)


# 3.保存当前一帧画面，验证是否渲染成功
# frame = event.frame
# img = Image.fromarray(frame)
# img.save("test_render.png")
frame = controller.last_event.frame
Image.fromarray(frame).save("final.png")
print("✅ 画面渲染成功，已保存为 test_render.png")



# 4.清理资源
controller.stop()
print("🎉 全部验证通过，AI2-THOR 安装完美！")

