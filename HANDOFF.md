# 乐小读 Day 4 顾问建议工作台交接

更新时间：2026-08-03

## 当前基线

- 当前分支：`main`。
- 本轮开发起点：`921c250`（`fix: normalize OCR speaker before advice generation`）。
- 已确认该起点包含完整 Day 4 顾问建议工作台。
- 本轮新增可审核、可暂停恢复的增量知识导入与链接图，并完成首批16份课程资料的本地整理和应用。

## 2026-08-03 知识导入与资料整理

### 首批知识成果

- 完整读取16份DOCX的正文、表格、关系超链接和473张嵌入图片，图片使用本地文档模式OCR。
- 整理形成17份 `policy/产品知识` 文件和4份 `style_case/顾问沟通` 文件；连同原有知识，本地正式索引为23个文档、146个切片。
- 只保留顾问对客信息；内部负责人、业务指标、培训排期和内部链接没有进入可检索正文。
- 当前链接基线为96次引用、89个唯一资料；5个稳定链接已与本批本地来源精确关联，未入库资料为84份。
- `knowledge/`、`data/` 和 `artifacts/` 仍按隐私策略由 `.gitignore` 排除，不会随代码推送；本地最终审核报告保留在应用批次目录。

### 增量导入工作流

- `--prepare-knowledge-import`：递归扫描配置来源目录，生成提取结果、审核文件、报告和增量草稿，不修改正式知识。
- `--resume-knowledge-import <BATCH_ID>`：按文件检查点继续暂停批次，复用已完成提取和图片OCR缓存。
- `--apply-knowledge-import <BATCH_ID>`：只应用已审核的来源映射和草稿，检查知识基线哈希后写入正式目录并自动重建索引。
- `--knowledge-link-report`：输出链接引用次数、唯一目标、已入库/未入库数量和资料类型分布。
- 来源支持DOCX、XLSX和PDF：DOCX读取正文、表格、图片及关系链接；XLSX读取单元格、批注、单元格链接和 `HYPERLINK` 公式；文本PDF读取正文与链接注释，扫描PDF使用本地OCR。
- 来源使用SHA-256识别新增、修改、重命名和未变化文件；未变化来源不重复提取或OCR，移走来源只标记缺失，不自动删除已审核知识。
- 建议输出路径从文件名动态提取年份和季节；信息不足时标记“时期待确认”。已有目标知识会复制到草稿区作为合并底稿，正式文件在审核应用前保持不变。
- 链接按规范化URL去重，引用边保留来源、定位、显示文字、上下文和次数；只有稳定链接与本地标题完全匹配并经审核后才建立别名，不使用模糊标题自动入库，也不自动访问或下载链接。

### 清理结果

- 删除旧OCR工作目录中的473张临时PNG、旧提取结果、临时脚本和日志。
- 删除测试临时目录、Python/pytest缓存、未引用预览图、重复验证批次和已应用批次中的提取/草稿中间文件，约释放300.8MB。
- 保留23个正式知识文件、知识/反馈数据库、项目虚拟环境、源码、测试源码和最终审核报告。
- 删除重复批次记录后，SQLite仅保留已应用批次，来源 `last_seen_batch` 没有断链。

## 本轮完成范围

### 真实检索驱动的生成流程

- `AdviceService` 对每次对话分别执行 `policy` 和 `style_case` 真实检索，再调用 Generator；生成器不能绕过检索流程。
- 默认 `SimulatedGenerator` 不需要 API。检索到制度依据时，顾虑摘要和微信短回复会使用排名第一的真实文档、定位和证据；没有制度依据时只建议转人工核实，不编造事实。
- 建议卡的事实依据直接绑定 `SearchResult`，不接受生成器或未来模型自行返回引用。
- 手动问题和 OCR 校正对话使用同一条后台生成链路，生成期间不阻塞 Qt 主线程。
- OCR 完成后必须由顾问点击“确认无误并生成建议”才会启动建议服务；展示校正结果本身不会触发生成。
- Qt 编辑器可能将发言人枚举作为 `"家长"`/`"顾问"` 字符串返回；`TranscriptLine` 会在数据边界统一转换为 `Speaker`，避免确认后组装检索文本时异常并永久停在生成状态。
- 建议任务的同步提交错误会直接显示在结果窗口和悬浮工具条，不再静默等待。
- 知识索引缺失或检索失败时，工作台和悬浮工具条都会显示明确错误状态。

### 可替换 Generator 与豆包兼容准备

- `Generator` 是厂商无关的 Protocol，统一输入 `GenerationRequest`，输出 `SuggestionDraft`。
- `OpenAICompatibleGenerator` 接受注入的 client 和 model，调用 `client.chat.completions.create(...)` 并要求 JSON 对象响应。
- 当前计划接入豆包时，只需在应用装配层提供配置好 base URL、密钥和模型的 OpenAI 兼容 client。
- 更换其他 OpenAI 兼容服务不影响检索、风险、反馈和 UI；非兼容协议可新增 Generator 适配器。
- 当前仓库仍不要求真实 API，不安装厂商 SDK，不读取或提交 API Key。

### 完整顾问建议工作台

- 每条结构化建议包含：
  - 顾虑摘要；
  - 可直接编辑的微信短回复；
  - 带文档名和章节/页码的事实依据；
  - 风险等级及逐条风险提示；
  - 明确的转人工状态。
- 工作台保留底部输入区、Enter 发送、Shift+Enter 换行、多轮记录和关闭后重新打开的进程内历史。
- 悬浮工具条“AI 问答”继续打开带输入框的手动提问窗口。
- 截图 OCR 校正确认后打开独立的“顾问建议”结果窗口，隐藏提问框并直接展示生成状态和后续建议，不会跳入手动 AI 问答流程。
- 保留 `append_ai_response(text)` 作为旧纯文本调用的兼容入口。

### 确定性风险与复制门控

- 风险判断完全由本地 `DeterministicRiskRules` 执行，不采信生成模型给出的风险等级。
- 高风险规则：退款/投诉/法律争议、人身安全/健康、隐私/个人信息、体罚/欺凌等儿童保护事件。
- 没有 `policy` 权威依据时固定判为高风险并要求转人工。
- 费用、合同、请假、补课、转班及保证性表述等命中中风险并建议人工复核。
- 其他有制度依据且未命中规则的建议为低风险。
- 高风险卡片的复制按钮默认禁用；顾问勾选“已阅读风险提示”后才可一键复制当前编辑内容。

### 隐私安全反馈

- 顾问可选择“有用”或“无用”，并从与选择匹配的枚举原因中提交反馈。
- `FeedbackStore` 将反馈写入独立 SQLite 数据库，字段仅有建议 ID、有用状态、枚举原因和时间戳。
- 反馈表没有聊天、家长问题、OCR 对话或生成回复正文字段。
- 默认反馈路径：`data/feedback.sqlite3`，由 `[feedback].database_path` 配置。

## 主要接口

- `AdviceService.create(transcript)`：真实检索、生成、事实绑定和风险判断的同步核心服务。
- `Generator.generate(request)`：可替换生成器边界。
- `SimulatedGenerator`：默认的本地确定性实现。
- `OpenAICompatibleGenerator(client, model)`：豆包等 OpenAI 兼容服务适配器。
- `DeterministicRiskRules.assess(...)`：确定性风险和转人工判断。
- `AiChatDialog.append_suggestion(suggestion)`：追加完整结构化建议卡。
- `FeedbackStore.save(submission)`：只持久化结构化反馈元数据。
- `CaptureController.transcript_ready`、`ai_question_submitted` 和 `append_ai_response`：继续兼容 Day 3 接口。
- `KnowledgeImportService.prepare(source_dir)`：扫描来源增量、提取文档、更新链接图并生成审核批次。
- `KnowledgeImportService.resume(batch_id, source_dir)`：从文件级检查点继续暂停批次。
- `KnowledgeImportService.apply(batch_id)`：应用审核草稿、来源映射和稳定链接别名，并重建正式索引。
- `KnowledgeImportService.link_report()`：查询当前全量链接入库统计。

## 主要文件

- `src/lexiaodu/advice.py`：检索、生成、风险编排及结构化建议。
- `src/lexiaodu/generator.py`：Generator Protocol、本地模拟实现和 OpenAI 兼容适配器。
- `src/lexiaodu/risk.py`：确定性风险规则与转人工状态。
- `src/lexiaodu/feedback.py`：隐私安全的反馈数据模型和 SQLite 存储。
- `src/lexiaodu/chat.py`：完整建议卡、编辑、复制门控和反馈交互。
- `src/lexiaodu/workflow.py`：手动问题/OCR 到建议工作台的后台链路。
- `src/lexiaodu/app.py`：默认本地服务装配。
- `src/lexiaodu/knowledge_import.py`：DOCX/XLSX/PDF增量提取、OCR协调、来源状态、链接图、审核和应用事务。
- `src/lexiaodu/ocr.py`：聊天OCR与不使用聊天布局过滤的文档OCR模式。
- `src/lexiaodu/knowledge.py`：分类BM25检索；文档名、章节和正文共同参与排序。
- `config/app.toml`：默认来源目录、审核暂存目录和本地知识路径。
- `tests/test_generator.py`、`tests/test_risk.py`、`tests/test_feedback.py`：Day 4 核心逻辑测试。
- `tests/test_chat.py`、`tests/test_workflow.py`：工作台和悬浮工具端到端交互回归。
- `tests/test_knowledge_import.py`：格式提取、链接规范化、审核门槛、增量草稿、暂停恢复和链接入库测试。

## 验证命令

```powershell
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider --basetemp artifacts\pytest-final-push
.\.venv\python.exe -m compileall -q src tests
.\.venv\python.exe -m pip check
.\.venv\python.exe -B -m lexiaodu --knowledge-link-report
git diff --check
```

2026-08-03 最终结果：

- 完整测试：77 tests passed。
- Python 编译检查：通过。
- 依赖一致性：`No broken requirements found`。
- 真实链接报告：96次引用、89个唯一资料、5个已入库、84个未入库。
- 差异空白检查：通过；仅有 Git 的 LF/CRLF 工作区提示。
- 截图选区定时测试为80ms产品延迟保留250ms测试等待窗口，避免Windows定时调度抖动；产品行为未改变。

## 已知边界与后续工作

- 豆包真实 client、base URL、模型和密钥尚未装配；当前只完成可替换接口和 OpenAI 兼容适配器。
- 风险规则是保守的确定性关键词规则；新业务风险类型需要显式补规则和测试。
- 通过审核导入命令应用知识时会自动重建索引；直接手工编辑 `knowledge/` 后仍需执行 `--rebuild-knowledge`。
- 增量来源导入支持扫描PDF OCR；直接把扫描PDF放入正式 `knowledge/` 仍不能由基础索引器OCR。
- 旧版 `.xls` 不直接支持，需要先转换为 `.xlsx`。
- 知识草稿必须经人工或Codex审核；提取失败、时期待确认、事实冲突和仅标题相似的链接不能自动进入正式知识。
- 内部链接只记录在本地元数据和审核报告中，导入器不会自动访问或下载。
- 聊天和建议历史仅驻留当前进程；只有结构化反馈会持久化。
