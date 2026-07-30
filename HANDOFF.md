# 乐小读 OCR 与 AI 问答功能交接

更新时间：2026-07-30

## 当前基线

- 当前分支：`main`。
- 本轮开发基于提交 `0509edf`（`feat: implement Day 3 local knowledge retrieval`）。
- 本轮覆盖截图 OCR 性能与稳定性、聊天界面误识别过滤，以及顾问手动输入家长问题的网页端 AI 问答入口。

## 本轮完成范围

### 截图 OCR 性能与稳定性

- 应用启动后使用单独的 OCR 工作线程预加载 PaddleOCR 模型，避免第一次截图后才加载模型。
- 截图识别在后台线程执行，主界面不会在模型推理期间阻塞。
- OCR 运行期间禁止重复启动截图选择；识别完成后恢复正常流程。
- 文字检测阶段将最长边限制为 1600 像素，降低大尺寸聊天截图的检测耗时，输出坐标仍对应原图。
- 设置 `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`，避免启动时进行不必要的模型源连通性检查。
- 修复关闭截图相关窗口后应用进程提前退出的问题；只有点击工具栏“关闭”或正常退出应用时才关闭 OCR 工作线程。
- OCR 不可用或识别失败时仍打开手动粘贴校正窗口，并显示明确状态。

### 昵称、时间与引用消息过滤

- 保留原有置信度、左右边缘和画面中心区域过滤规则。
- 新增文字框局部亮度对比度检测，过滤微信界面中的浅灰昵称、时间戳和引用预览。
- 正常的深色家长消息、顾问消息以及绿色消息气泡内的深色正文会被保留。
- OCR 校正窗口确认后，通过统一的 `transcript_ready` 信号输出最终对话数据。

### 网页端 AI 单列问答工作台

- 工具栏新增“AI 问答”入口，顾问可以不截图，直接手动输入家长问题。
- 对话采用类似网页端 AI 产品的居中单列内容流，不使用聊天软件式左右气泡。
- 每条内容包含“家长问题”或“AI”角色标题，以及可选择复制的纯文本正文。
- 家长问题和 AI 回复使用不同的浅色整行背景，但保持相同内容宽度与左对齐排版。
- 输入区固定在窗口底部；Enter 发送，Shift+Enter 换行，空白内容不会发送。
- 发送后显示等待 AI 回复状态，不生成模拟回答。
- 窗口关闭并重新打开后，当前进程内的多轮记录仍然保留；退出应用后不持久化。
- 手动问题同时通过 `ai_question_submitted(str)` 和统一的 `transcript_ready` 数据接口输出。

## 可复用接口

- `CaptureController.transcript_ready`：输出截图校正结果或手动输入的家长问题。
- `CaptureController.ai_question_submitted`：仅输出手动提交的问题文本。
- `CaptureController.append_ai_response(text)`：API 接入后将真实 AI 回复写入当前问答窗口。
- `AiChatDialog.question_submitted(str)`：窗口级问题提交信号。
- `AiChatDialog.messages`：读取当前进程内按时间排列的问答记录。
- `AiChatDialog.append_ai_response(text)`：按纯文本追加 AI 回复。

## 主要文件

- `src/lexiaodu/ocr.py`：OCR 预加载、检测尺寸限制和视觉元数据过滤。
- `src/lexiaodu/workflow.py`：后台 OCR 工作线程、结果信号、编辑器提交和 AI 问答控制。
- `src/lexiaodu/chat.py`：网页端单列 AI 问答界面与键盘行为。
- `src/lexiaodu/toolbar.py`：新增 AI 问答入口。
- `src/lexiaodu/app.py`：应用生命周期和 OCR 工作线程关闭。
- `README.md`：截图识别和手动 AI 问答使用说明。
- `tests/test_ocr.py`、`tests/test_workflow.py`、`tests/test_chat.py`：相关回归与交互测试。

## 验证命令

```powershell
.\.venv\python.exe -m pytest -q
.\.venv\python.exe -m compileall -q src tests
.\.venv\python.exe -m pip check
```

本轮最终验证结果：

- 完整测试：42 tests passed。
- Python 编译检查：通过。
- 依赖一致性检查：`No broken requirements found`。
- AI 问答离屏布局检查：单列整行内容流和固定输入区正常；离屏平台未加载中文字体，但控件 Unicode 文案已由自动化测试验证。

## 已知边界与后续工作

- AI API 尚未接入；目前只提交问题并显示等待状态，接入后调用 `append_ai_response()` 写入真实结果。
- 聊天记录仅保留在当前应用进程内，没有数据库持久化。
- 昵称和引用过滤基于浅灰文字的局部对比度启发式规则；不同微信主题、缩放比例或自定义配色可能需要继续调整阈值。
- PaddleOCR 仍是单工作线程串行推理，同一时间只处理一张截图。
- 扫描型 PDF 的知识库导入仍未接入 OCR，与本轮聊天截图 OCR 流程相互独立。
