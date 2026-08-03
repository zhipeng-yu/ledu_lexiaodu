# 乐小读

“乐小读”五日 MVP 的 Day 4 版本。除截图、OCR、校正和 Day 3 本地知识检索外，当前版本会用真实检索结果生成结构化顾问建议，并提供确定性风险提示、转人工状态、复制门控和匿名结构化反馈。

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

点击“AI 问答”可打开带输入框的手动问题分析窗口：

1. 顾问可手动输入完整的家长问题，并在居中的单列内容流中连续追问。
2. 每次发送都会先分别检索 `policy` 和 `style_case`，再把真实结果交给默认的本地模拟生成器。
3. 建议卡包含顾虑摘要、可编辑微信短回复、带文档和章节定位的事实依据、风险提示及转人工状态。
4. 低、中风险建议可一键复制编辑后的短回复；高风险建议必须先勾选风险确认，复制按钮才会启用。
5. 可选择“有用”或“无用”并提交枚举原因。反馈数据库只记录建议 ID、选择、原因和时间，不保存聊天或回复正文。
6. Enter 发送，Shift+Enter 换行；窗口关闭后重新打开仍保留当前进程内的工作台记录，退出后不持久化聊天正文。

截图 OCR 识别完成后会先停留在校正窗口，建议服务此时不会启动。顾问核对文字和发言人并点击“确认无误并生成建议”后，应用才会打开独立的“顾问建议”结果窗口；该窗口不显示手动提问框，也不要求再次输入，直接执行检索、生成和风险流程。若知识索引尚未建立，结果窗口会明确提示生成失败；先执行 `--rebuild-knowledge` 即可。

## Generator 兼容层

业务流程只依赖 `Generator.generate(GenerationRequest)`，不依赖具体厂商 SDK：

- `SimulatedGenerator` 是默认实现，不需要 API Key；有权威检索结果时，短回复直接使用排名第一的真实制度来源和证据，没有制度依据时只生成“转人工核实”回复。
- `OpenAICompatibleGenerator` 接受外部注入的 `client` 和 `model`，调用标准的 `client.chat.completions.create(...)`。当前计划接入豆包时，可在应用装配层配置兼容 client 的 base URL、密钥和模型；以后更换其他 OpenAI 兼容服务不需要修改检索、风险或界面代码。
- 若后续 API 不是 OpenAI 兼容协议，只需新增一个实现 `Generator` 的适配器。

仓库没有安装 OpenAI 或豆包 SDK，也不读取真实密钥。事实依据由应用直接绑定本地 `SearchResult`，不会采信模型生成的引用；风险等级也始终由本地确定性规则覆盖模型输出。

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

## 增量整理来源资料

来源资料目录和审核暂存目录由 `config/app.toml` 的
`knowledge_import.source_dir`、`knowledge_import.staging_dir` 配置。来源目录递归支持
DOCX、XLSX 和 PDF；DOCX 会读取正文、表格、图片 OCR 和超链接，XLSX 会读取工作表、
批注、单元格链接及 `HYPERLINK` 公式，扫描 PDF 会使用文档模式 OCR。旧版 `.xls`
需要先转换为 `.xlsx`。

将新资料放入来源目录后，先准备审核批次；此步骤不会修改正式知识文件或检索索引：

```powershell
.\.venv\python.exe -m lexiaodu --prepare-knowledge-import
```

每个批次会在暂存目录生成 `review.json`、`report.md`、完整提取文本和
`draft/knowledge/` 草稿。审核时为每个变化来源填写 `outputs`，或填写
`excluded_reason`；只有标题与稳定链接目标完全匹配时，才把候选项加入 `aliases`。
建议输出路径会从文件名提取年份和季节；信息不足时标记“时期待确认”，不能直接应用。
若建议目标已有正式知识，准备阶段会复制一份到草稿区作为增量合并底稿，正式文件保持不变。
提取文本不能直接当作正式知识，需先整理为面向顾问的短知识块，并排除内部人员、
业务指标、排期和内部链接。

审核完成后应用批次并自动重建索引：

```powershell
.\.venv\python.exe -m lexiaodu --apply-knowledge-import <BATCH_ID>
```

随时查看链接引用和未入库资料数量：

```powershell
.\.venv\python.exe -m lexiaodu --knowledge-link-report
```

准备过程中按 Ctrl+C 可以暂停。已完成文件和 OCR 缓存会保留，之后从文件检查点继续：

```powershell
.\.venv\python.exe -m lexiaodu --resume-knowledge-import <BATCH_ID>
```

文件 SHA-256 用于识别新增、修改、重命名和未变化来源；未变化文件不会重复提取或
OCR。移走来源只会标记“来源缺失”，不会自动删除已经审核的知识。

运行测试：

```powershell
.\.venv\python.exe -m pytest
```

截图坐标使用 Qt 的逻辑像素，并且必须完整落在同一个屏幕内。跨屏区域会被明确拒绝，不会被静默裁剪或拼接。
当前 OCR 过滤针对固定的左右气泡布局；若真实消息可能出现在画面中央或紧贴最外侧，需要调整策略或人工粘贴校正。

## 隐私与缓存

- 聊天截图不会写入磁盘，也没有截图历史记录。
- 手动问题、OCR 对话和生成回复只保留在当前应用进程内，退出后不会写入磁盘。
- `data/feedback.sqlite3` 仅保存建议 ID、有用状态、枚举原因和时间戳，表结构中没有聊天、问题或回复正文字段。
- OCR 模型权重是可复用开发缓存，不包含用户截图。
- 知识索引仅写入配置的本地 SQLite 文件；`policy` 与 `style_case` 检索在查询层强制隔离。
- PaddlePaddle 3.2 在 Windows 导入时会创建一个很小的 `%USERPROFILE%\.cache\paddle\dataset` 目录；模型权重仍使用上述 E 盘缓存。
- 确定性高风险规则覆盖退款/投诉/法律争议、人身安全/健康、隐私和儿童保护；没有权威制度检索结果时也按高风险处理并要求转人工。
