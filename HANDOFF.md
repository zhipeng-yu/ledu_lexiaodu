# 乐小读 Day 2 Handoff

更新时间：2026-07-29

## 开始门槛

- 开始前确认 `HEAD` 与 `origin/main` 均为 Day 1 最新提交 `78832d7`（`feat: bootstrap Day 1 MVP`）。
- Day 1 基线测试为 8 tests passed；工作区开始时无未提交改动。

## 完成范围

- 将悬浮工具的操作改为“框选截图”，新增覆盖虚拟桌面的半透明拖框选择层，支持 `Esc` 取消。
- 将截图协议改为只返回内存中的 `QImage`；删除截图目录创建、PNG 保存和输出路径字段。
- 接入本地 PaddleOCR 3.x CPU 推理，直接把 `QImage` 转换为 BGR `numpy.ndarray`，不经过临时图片文件。
- 固定使用轻量的 `PP-OCRv5_mobile_det` 和 `PP-OCRv5_mobile_rec` 模型，识别置信度阈值为 0.90。
- 针对固定左右气泡布局过滤非消息内容：删除完全落在左右最外侧
  3.5% 的头像/设备图标结果，以及中心位于画面 40%–60% 的时间戳或系统信息。
- 根据文字框中心位置做角色初判：画面左半边为“家长”，右半边（含中线）为“顾问”。
- 新增 OCR 校正窗口，可逐条修改文字和发言人、删除或添加发言，并显示 OCR 置信度。
- OCR 依赖缺失、模型不可用、推理失败或没有识别结果时，均打开校正窗口并提供手动粘贴文字、指定家长/顾问的兜底。
- 新增选区、内存截图结构、OCR 结果解析、角色判定、图像转换、校正 UI 和端到端控制器测试。

## 主要文件

- `src/lexiaodu/selection.py`：虚拟桌面拖框层和选区坐标归一化。
- `src/lexiaodu/capture.py`：只返回内存 `QImage` 的单屏截图协议与 Qt 实现。
- `src/lexiaodu/ocr.py`：PaddleOCR 延迟加载、`QImage` 到 BGR 数组转换、聊天内容过滤、结果解析和角色初判。
- `src/lexiaodu/editor.py`：OCR 文字/发言人校正及手动粘贴界面。
- `src/lexiaodu/workflow.py`：串联悬浮工具、选区、截图、OCR 和校正窗口的控制器。
- `src/lexiaodu/app.py`：Day 2 应用装配及纯内存截图烟测入口。
- `config/app.toml`：PaddleX 模型缓存目录，默认 `E:/DevCaches/paddlex`。
- `pyproject.toml`：可选 `ocr` 依赖组，固定 PaddleOCR 3.3.2 / PaddlePaddle 3.2.2。
- `tests/`：Day 1 测试及 Day 2 单元、UI、集成测试。

## 验证结果

- `.\.venv\python.exe --version`：Python 3.11.15。
- `.\.venv\python.exe -m pytest`：25 tests passed。
- `.\.venv\python.exe -m compileall -q src tests`：通过。
- `.\.venv\python.exe -m pip check`：No broken requirements found。
- PaddleOCR 模型级内存烟测：
  - PaddlePaddle 3.2.2、PaddleOCR 3.3.2。
  - 模型从 `E:\DevCaches\paddlex\official_models` 加载。
  - 从内存像素识别出 `PARENT HELLO`（0.984）和 `ADVISOR WELCOME`（0.987）。
  - 未创建输入、截图或 OCR 结果文件。
- `.\.venv\python.exe -m lexiaodu --capture-smoke`：通过；主屏
  `B160QAN02.7`，内存图像 720 × 405 物理像素，未生成图片文件。
- 固定左右布局样例回归：准确保留 `1234567`、`上课时间是什么`、
  `您好`、`123`、`456` 及对应角色，过滤 `16:45` 和头像图标假文字；
  本样例消息精确率与召回率均为 100%。

## 已知问题与 Day 2 边界

- OCR 过滤和角色判断针对固定左右气泡布局；中央消息、紧贴最外侧的消息、
  不同聊天软件或左右身份相反的界面仍可能需要人工校正。
- 仍只支持完整落在单个屏幕内的框选区域；跨屏框选会明确报错。
- OCR 初始化和推理当前在 GUI 主线程执行，首次模型加载期间界面可能暂时无响应。
- 首次 OCR 需要联网下载模型；缓存完成后可从本地模型运行。
- PaddlePaddle 3.2 在 Windows 导入时会创建 `%USERPROFILE%\.cache\paddle\dataset` 小目录；模型权重已放在 E 盘缓存。
- 截图和校正后的文本都未持久化；校正结果尚未进入 Day 3 的后续处理。
- 受限桌面会话可能让真实屏幕采集得到黑图；纯函数、UI 结构和工作流已自动测试。

## 后续可复用接口

- 截图来源继续实现 `lexiaodu.capture.ScreenCapture`，输入 `ScreenRegion`，输出包含内存 `QImage` 的 `CaptureResult`。
- OCR 来源可实现 `lexiaodu.ocr.OcrEngine`，输出 `TranscriptLine` 列表，无需修改工作流。
- `TranscriptEditor.transcript()` 可取得人工校正后的发言列表，供 Day 3 接续处理。
- `Speaker.PARENT` / `Speaker.ADVISOR` 是统一的家长/顾问标识。
