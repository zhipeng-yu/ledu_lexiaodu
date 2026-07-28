# 乐小读 Day 1 Handoff

更新时间：2026-07-28

## 完成范围

- 初始化 `main` 分支 Git 仓库，并配置 Python、测试、构建、编辑器和运行产物忽略规则。
- 创建项目内 `.venv`，实际版本为 Python 3.11.15；未修改或安装依赖到 Conda base。
- 建立 `src/lexiaodu` 模块化骨架，以及 TOML 配置、领域数据结构和两篇虚构中文演示资料。
- 实现 PySide6 无边框、可拖动、置顶悬浮工具条，提供“截图验证”和“关闭”两个最小操作。
- 通过 `ScreenCapture` 协议隔离截图接口，实现 Qt 单屏区域截图适配器；跨屏区域会明确报错。
- 提供模块入口、控制台脚本入口、截图烟测参数和基础测试。

## 主要文件

- `pyproject.toml`：Python 版本、运行/开发依赖、入口和 pytest 配置。
- `config/app.toml`：工具条尺寸、位置边距和截图区域配置。
- `demo/reading_materials.json`：仅用于开发的虚构演示资料。
- `src/lexiaodu/domain.py`：`ScreenRegion`、`ReadingMaterial` 及居中区域计算。
- `src/lexiaodu/config.py`：基于 Python 3.11 `tomllib` 的类型化配置加载。
- `src/lexiaodu/capture.py`：截图协议、结果结构和 PySide6 单屏实现。
- `src/lexiaodu/toolbar.py`：最简置顶悬浮工具条。
- `src/lexiaodu/app.py`：应用装配、运行入口和截图烟测入口。
- `tests/`：领域、配置、演示数据、截图边界和工具条窗口标志测试。

## 验证结果

- `.\.venv\python.exe --version`：Python 3.11.15。
- `.\.venv\python.exe -m pytest`：8 tests passed。
- `.\.venv\python.exe -m compileall -q src tests`：通过。
- `.\.venv\python.exe -m pip check`：无依赖冲突。
- `.\.venv\python.exe -m lexiaodu --capture-smoke artifacts\day1-smoke.png`：通过。
  - 主屏：`B160QAN02.7`
  - 请求区域：480 × 270 Qt 逻辑像素
  - 输出图像：720 × 405 物理像素（屏幕缩放 150%）
  - 已检查图像内容非空；文件保留在本地并由 Git 忽略。

## 已知问题与 Day 1 边界

- 目前只支持 Windows 上由 Qt 提供的单屏截图；不支持跨屏拼接。
- 当前截图区域由配置固定为主屏中央区域，没有交互式框选、预览或历史记录。
- OCR、内容识别、阅读过程和反馈功能均未实现，留待 Day 2–5。
- 受限沙箱会阻止桌面采集并产生黑图；真实截图烟测需要在可访问交互桌面的会话中运行。
- 工具条窗口标志和构造已自动测试，但尚未覆盖不同 Windows 缩放率和多显示器排列的人工 UI 回归。

## 后续可复用接口

- 后续截图来源可实现 `lexiaodu.capture.ScreenCapture`，无需修改调用方。
- 捕获请求使用逻辑桌面坐标 `ScreenRegion`，当前适配器负责转换为屏幕本地坐标。
- 阅读资料以 `ReadingMaterial` 表示，演示 JSON 通过 `load_demo_materials` 进入领域层。
