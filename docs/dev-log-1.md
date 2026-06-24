# 环境配置
Ubuntu 24.04 + ROS2 jazzy

ROS2的安装参考鱼香ROS的教程

## 检查 ROS2 Jazzy 是否正常
```
lsb_release -a
echo $ROS_DISTRO
which ros2
ros2 --version
```
## 安装 MoveIt2 和基础工具
```
sudo apt update
sudo apt install -y \
  ros-jazzy-moveit \
  ros-jazzy-rmw-cyclonedds-cpp \
  python3-colcon-common-extensions \
  python3-vcstool \
  python3-rosdep \
  git \
  build-essential
```
检查：
```
ros2 pkg list | grep moveit | head
```
能看到一堆 moveit 包就说明 MoveIt2 装上了
> 这里其实还需要装几个依赖，然后启动RViz2的时候才能不报process died错误，但是装的是哪几个包我忘记了。
如果遇到了，解决办法是：把RViz2的运行日志全丢给AI，让他告诉你需要安装什么。（没错就是这么简单直接）

## 跑 Panda demo
```
sudo apt install -y \
  ros-jazzy-moveit-resources-panda-description \
  ros-jazzy-moveit-resources-panda-moveit-config
```
## 启动RViz2
```
ros2 launch moveit_resources_panda_moveit_config demo.launch.py
```
好了，到此为止你应该能收获一个可移动的机械臂了。
![alt text](<imgs/截图 2026-06-10 13-23-06.png>)


# 跑通后立刻建项目目录

MoveIt demo 跑通后，建我们的项目工程：
```
mkdir -p ~/nl2manip_ws/{configs,examples,src,scripts,demos,docs}
cd ~/nl2manip_ws
```

创建对象表：
```
cat > configs/objects.json <<'EOF'
[
  {
    "id": "red_cube_1",
    "type": "cube",
    "color": "red",
    "pose": [0.45, 0.20, 0.04]
  },
  {
    "id": "blue_cube_1",
    "type": "cube",
    "color": "blue",
    "pose": [0.45, -0.20, 0.04]
  },
  {
    "id": "green_cylinder_1",
    "type": "cylinder",
    "color": "green",
    "pose": [0.55, 0.10, 0.04]
  },
  {
    "id": "blue_box_1",
    "type": "box",
    "color": "blue",
    "pose": [0.60, -0.25, 0.04]
  },
  {
    "id": "green_box_1",
    "type": "box",
    "color": "green",
    "pose": [0.60, 0.25, 0.04]
  },
  {
    "id": "table_center",
    "type": "table_center",
    "color": null,
    "pose": [0.50, 0.00, 0.04]
  }
]
EOF
```
创建第一个 DSL 任务：
```
cat > examples/pick_red_cube_to_blue_box.json <<'EOF'
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
EOF
```

1. 今天最终验收

今天结束前，你应该能做到两个结果。

第一个是 MoveIt2 / RViz demo：
```
ros2 launch moveit_resources_panda_moveit_config demo.launch.py
```
或者：
```
ros2 launch moveit2_tutorials demo.launch.py
```
然后在 RViz 里完成一次：

`拖目标位姿 → Plan → Execute`

第二个是项目文件准备好：

`tree ~/nl2manip_ws`

大概长这样：
```
nl2manip_ws/
├── configs/
│   └── objects.json
├── examples/
│   └── pick_red_cube_to_blue_box.json
├── src/
├── scripts/
├── demos/
└── docs/
```
