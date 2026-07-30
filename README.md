# 乐小读

“乐小读”五日 MVP 的 Day 3 版本。除 Day 2 的截图、OCR 与校正流程外，当前版本可从本地 TXT、DOCX 和文本型 PDF 建立知识索引，并按 `policy`（权威知识）或 `style_case`（风格案例）进行互不混合的 BM25 检索。

## 环境

项目固定使用 Python 3.11，并将环境放在仓库内的 `.venv`。在 PowerShell 中从项目根目录执行：

```powershell
$env:CONDA_PKGS_DIRS = 'E:\DevCaches\conda-pkgs'
conda --no-plugins create --prefix .\.venv --solver classic python=3.11 pip -y
$env:PIP_CACHE_DIR = 'E:\DevCaches\pip'
.\.venv\python.exe -m pip install -e ".[dev,ocr]" --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

这些命令不会安装依赖到 Conda base。若仅需运行无 OCR 的手动粘贴兜底和知识检索，可安装 `.[dev]`；应用会在 PaddleOCR 不可用时自动降级。

PaddleOCR 首次运行会下载 PP-OCRv5 mobile 检测和识别模型。默认模型缓存为 `E:\DevCaches\paddlex`，可在 `config/app.toml` 的 `ocr.model_cache_dir` 中修改。

## 运行

启动置顶悬浮工具条：

```powershell
.\.venv\python.exe -m lexiaodu
```

点击“框选截图”后拖动鼠标选择一个聊天区域：

1. 截图以 `QImage` 保留在当前进程内，不保存图片或临时文件。
2. 应用启动后会在专用线程预加载 OCR 模型；截图完成后，PaddleOCR 在该线程中直接接收内存像素数组，不阻塞界面。
3. 宽边超过 1600 像素的截图会在文字检测阶段等比限边，识别结果仍按原图坐标返回。
4. 低于 90% 置信度、完全位于左右最外侧 3.5%、中心位于画面
   40%–60% 区域，或呈现为低对比度浅灰色的结果，会作为图标、时间戳、昵称、引用预览等非消息内容过滤。
5. 其余文字框中心在画面左半边时初判为“家长”，右半边时初判为“顾问”。
6. 在 OCR 校正窗口中可编辑文字和发言人；OCR 不可用或遗漏时，可粘贴文字并指定发言人。

点击“AI 问答”可打开网页端 AI 单列问答工作台：

1. 顾问可手动输入完整的家长问题，并在居中的单列内容流中连续追问。
2. 每次发送都会作为“家长”发言输出到统一的待分析数据接口。
3. Enter 发送，Shift+Enter 换行；问题和 AI 回复均以可复制的纯文本显示。
4. 对话记录在窗口关闭并重新打开后仍会保留，直到应用退出。
5. 当前 AI API 尚未接入，界面会明确显示等待状态，不会生成虚假回答；后续可通过控制器的 `append_ai_response()` 写入真实 AI 回复。

执行一次主屏幕中央区域的纯内存截图烟测：

```powershell
.\.venv\python.exe -m lexiaodu --capture-smoke
```

## 本地知识库

在配置的知识根目录下建立两个分类子目录。支持继续在分类目录中建立更深层级，但可索引文档不能放在这两个分类之外：

```text
knowledge/
├── policy/       # 制度、产品规则等权威知识
└── style_case/   # 仅用于参考表达方式的案例
```

支持 UTF-8 TXT、DOCX 和文本型 PDF；扫描型 PDF 不做 OCR，会在重建时明确报错。TXT 与 DOCX 按标题记录章节，PDF 按页记录页码，长内容切分为不超过 500 字符的切片。文档和切片的来源元数据保存在本地 SQLite `data/knowledge.sqlite3` 中。

重建整个本地索引：

```powershell
.\.venv\python.exe -m lexiaodu --rebuild-knowledge
```

检索时必须显式选择知识类型，最多返回 3 条 BM25 结果。每条结果包含文档名、章节或页码以及证据片段：

```powershell
.\.venv\python.exe -m lexiaodu --search "请假流程" --knowledge-type policy
.\.venv\python.exe -m lexiaodu --search "如何温和表达" --knowledge-type style_case
```

也可以先重建后立即检索：

```powershell
.\.venv\python.exe -m lexiaodu --rebuild-knowledge --search "请假流程" --knowledge-type policy
```

运行测试：

```powershell
.\.venv\python.exe -m pytest
```

截图坐标使用 Qt 的逻辑像素，并且必须完整落在同一个屏幕内。跨屏区域会被明确拒绝，不会被静默裁剪或拼接。
当前 OCR 过滤针对固定的左右气泡布局；若真实消息可能出现在画面中央或紧贴最外侧，需要调整策略或人工粘贴校正。

## 隐私与缓存

- 聊天截图不会写入磁盘，也没有截图历史记录。
- 手动 AI 问答记录只保留在当前应用进程内，退出后不会写入磁盘。
- OCR 模型权重是可复用开发缓存，不包含用户截图。
- 知识索引仅写入配置的本地 SQLite 文件；`policy` 与 `style_case` 检索在查询层强制隔离。
- PaddlePaddle 3.2 在 Windows 导入时会创建一个很小的 `%USERPROFILE%\.cache\paddle\dataset` 目录；模型权重仍使用上述 E 盘缓存。
- 当前校正结果只驻留在校正窗口中；知识检索通过独立 API/CLI 使用，尚未由 OCR 校正窗口自动触发。
