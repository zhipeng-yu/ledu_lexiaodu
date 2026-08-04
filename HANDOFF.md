# 乐小读项目交接

更新时间：2026-08-04

## 2026-08-04 双层全量知识库

### 已完成架构

- 保留 `knowledge/policy` 与 `knowledge/style_case` 整理层，在同一个 `data/knowledge.sqlite3` 中新增来源修订、原始内容块、原文切片和 SQLite FTS5 索引；原始二进制文件仍留在外部来源目录。
- `--prepare-knowledge-import` 只写待审核修订、逐块审核清单、覆盖报告和整理差异草稿；`--apply-knowledge-import` 原子启用审核修订并重建两层索引。来源修改但未审核、或文件暂时移走时，旧审核版本继续可用。
- 每个提取对象在 `review.json` 的 `raw.block_candidates` 中带稳定块 ID、定位、类型、字符数、预览、受众、质量、OCR 置信度和警告。审核可按来源、定位或块覆盖为顾问可用、仅内部、阻断、无文字或失败，禁止静默遗漏。
- 来源递归支持 DOCX、XLSX、PPTX、文本/扫描 PDF、PNG、JPG/JPEG 和 WebP；`.doc`、`.xls`、`.ppt` 进入转换清单。Office 深层结构、链接、替代文字和嵌入图片 OCR 均保留定位。
- `顾问聊天记录/**` 是配置级排除路径。本任务没有读取、OCR、修改或入库其中 3 张聊天截图；顾问语气任务拥有 `src/lexiaodu/generator.py`、`tests/test_generator.py` 及相关风格资料，本任务未编辑或提交这些文件。
- `KnowledgeType.SOURCE` 只返回已审核、顾问可用、质量合格的原文；`--include-internal` 只用于本机审计。链接 URL 保留在引用图和报告中，不进入顾问证据。
- `AdviceService` 在不改变 Generator 接口的前提下统一排序整理 `policy` 与审核原文，相关度接近时优先整理知识，精确原文用于补足表格、图片和未整理细节。
- 新增 `--knowledge-coverage-report`；链接报告现区分已归档、顾问可用、仅内部和未入库资料。Windows 控制台无法编码个别 OCR 符号时会安全替换，不再中断检索。

### 首批 16 份资料迁移

- 已应用批次：`20260804T043436Z-5b70fd81`。16 个来源均有审核修订，整理层仍为 23 个文档、146 个切片。
- 原文层共 1,908 个内容块、213,676 个字符；顾问可检索 192,682 字符、1,696 个块，仅内部 212 个块，待审核 0 个。
- 473 个 Word 内嵌图片全部有状态：467 个 OCR 有文字，6 个明确无文字；提取失败 0 个，低可信或事实风险阻断 4 个。
- 第二轮受众审计额外隔离了内部联络说明、员工编号表、企业微信外部群截图、学员画像示例，以及带联系方式/企业微信入口的教师介绍图；内容仍可审计，但不会传给顾问回复。
- 链接基线保持 96 次引用、89 个唯一目标；5 个目标已归档且顾问可用，84 个仍未入库。导入器不自动访问或下载链接。
- 代表性原文检索已验证图片信息：`初中数学 第1讲` 优先返回课程目录图片 OCR，`彭睿老师 高考物理满分` 返回物理教师介绍图片 OCR；内部续报目标默认不可检索，增加 `--include-internal` 才可审计。
- 本地审核文件和报告保留在 `artifacts/knowledge-import/20260804T043436Z-5b70fd81/`；应用后临时全文和草稿目录均已删除。`knowledge/`、`data/`、真实资料和审核 artifacts 继续由 Git 忽略。

### 主要新增验证

- DOCX 正文/表格/页眉/全部媒体对象，XLSX 单元格/公式/批注/链接，PPTX 幻灯片/备注/链接/媒体，文本与扫描 PDF，独立图片和 OCR 质量门槛。
- 顾问/内部隔离、人工冲突阻断、链接 URL 排除、来源标题与精确短语排序、旧版继续服务与审核后原子切换、来源缺失保留旧版本、暂停恢复和旧格式转换清单。
- 完整测试、编译、依赖和 Git 差异检查结果见本文件末尾最新验证记录。

## Day 5 最终集成

- 本轮开发起点：`51fa99f`（`feat: add incremental knowledge import`），已确认包含 Day 4 主提交 `eb655f9` 及修复 `3d35421`、`921c250`。
- 完整自动化验收覆盖截图、OCR 校正与粘贴、真实检索、建议、高风险确认、编辑复制和结构化反馈。
- 隐私验收确认截图流程不新增文件，日志和反馈库均不包含测试聊天正文或编辑后回复；反馈表仍只有五个元数据字段。
- 四组固定查询的目标资料均在当前正式索引排名第 1；可用 `scripts/verify_day5_queries.py` 重复验证。
- 已通过 `.env` 装配火山方舟 OpenAI 兼容接口；`scripts/verify_doubao.py` 使用虚构内容验证真实鉴权、`doubao-seed-2-0-lite-260215` 和 JSON 结构化输出，关闭深度思考后推送前复测 8.81 秒。
- AI 问答输入框兼容中文输入法组合态：拼音组词期间隐藏占位文字，提交或取消组合后恢复，避免占位提示与候选文字重叠。
- README、安装运行说明、五分钟演示脚本、指定电脑手动清单、顾问试用表和验收结果已经补齐。
- 最终代码验证为 87 tests passed，Python 编译和依赖检查通过，Qt 当前会话内存截图烟测通过。
- 启用豆包时，OCR 校正对话和本次知识检索片段会发送给火山方舟；Key 只存在被 Git 忽略的本机 `.env`，但正式使用前仍需确认外部数据处理要求。
- 最终指定演示电脑的真实聊天 OCR、DPI 缩放和剪贴板肉眼验证，以及真实顾问试用，仍须按 `docs/MANUAL_TEST_CHECKLIST.md` 和 `docs/ADVISOR_TRIAL_FORM.md` 执行。

## Day 4 基线

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

- `AdviceService` 对每次对话执行整理 `policy`、审核原文兜底和 `style_case` 真实检索，再调用 Generator；生成器不能绕过检索流程。
- 默认 `SimulatedGenerator` 不需要 API。检索到制度依据时，顾虑摘要和微信短回复会使用排名第一的真实文档、定位和证据；没有制度依据时只建议转人工核实，不编造事实。
- 建议卡的事实依据直接绑定 `SearchResult`，不接受生成器或未来模型自行返回引用。
- 手动问题和 OCR 校正对话使用同一条后台生成链路，生成期间不阻塞 Qt 主线程。
- OCR 完成后必须由顾问点击“确认无误并生成建议”才会启动建议服务；展示校正结果本身不会触发生成。
- Qt 编辑器可能将发言人枚举作为 `"家长"`/`"顾问"` 字符串返回；`TranscriptLine` 会在数据边界统一转换为 `Speaker`，避免确认后组装检索文本时异常并永久停在生成状态。
- 建议任务的同步提交错误会直接显示在结果窗口和悬浮工具条，不再静默等待。
- 知识索引缺失或检索失败时，工作台和悬浮工具条都会显示明确错误状态。

### 可替换 Generator 与真实豆包接入

- `Generator` 是厂商无关的 Protocol，统一输入 `GenerationRequest`，输出 `SuggestionDraft`。
- `OpenAICompatibleGenerator` 接受注入的 client、model、token 上限和额外请求参数，调用 `client.chat.completions.create(...)` 并要求 JSON 对象响应。
- 应用从本机 `.env` 读取 `LEXIAODU_GENERATOR`、`ARK_BASE_URL`、`ARK_MODEL` 和 `ARK_API_KEY`；选择 `doubao` 时装配火山方舟 OpenAI 兼容 client，选择 `simulated` 或未配置时使用本地生成器。
- 豆包装配会校验 Key 非空且仅含 ASCII、模型非空和 HTTPS base URL；远端调用失败时明确报错，不静默回退到模拟建议。
- `scripts/verify_doubao.py` 复用正式应用装配链路，以虚构内容完成真实鉴权、模型调用和 JSON 结构验证，不输出 Key 或生成正文。
- 更换其他 OpenAI 兼容服务不影响检索、风险、反馈和 UI；非兼容协议可新增 Generator 适配器。
- `openai` 和 `python-dotenv` 已作为项目依赖；真实 Key 只保存在被 Git 忽略的 `.env`，仓库仅提交 `.env.example`。

### 完整顾问建议工作台

- 每条结构化建议包含：
  - 顾虑摘要；
  - 可直接编辑的微信短回复；
  - 带文档名和章节/页码的事实依据；
  - 风险等级及逐条风险提示；
  - 明确的转人工状态。
- 工作台保留底部输入区、Enter 发送、Shift+Enter 换行、多轮记录和关闭后重新打开的进程内历史。
- 中文输入法处于拼音组合态时，输入框暂时隐藏占位提示，组合完成或取消后恢复，不影响 Enter 和 Shift+Enter 行为。
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
- `KnowledgeImportService.coverage_report()`：查询来源修订、对象、字符、图片 OCR、无文字、失败和阻断覆盖。
- `KnowledgeBase.search(..., KnowledgeType.SOURCE)`：检索审核通过的顾问原文；`include_internal=True` 仅用于本机审计。
- `KnowledgeBase.search_advice_policy(...)`：统一排序整理知识与审核原文，供 `AdviceService` 使用。

## 主要文件

- `src/lexiaodu/advice.py`：检索、生成、风险编排及结构化建议。
- `src/lexiaodu/generator.py`：Generator Protocol、本地模拟实现和 OpenAI 兼容适配器。
- `src/lexiaodu/risk.py`：确定性风险规则与转人工状态。
- `src/lexiaodu/feedback.py`：隐私安全的反馈数据模型和 SQLite 存储。
- `src/lexiaodu/chat.py`：完整建议卡、编辑、复制门控和反馈交互。
- `src/lexiaodu/workflow.py`：手动问题/OCR 到建议工作台的后台链路。
- `src/lexiaodu/app.py`：本地模拟或真实豆包生成器的环境配置、校验和服务装配。
- `src/lexiaodu/knowledge_import.py`：DOCX/XLSX/PPTX/PDF/图片增量提取、OCR协调、来源修订、逐块审核、FTS5 原文索引、链接图和应用事务。
- `src/lexiaodu/ocr.py`：聊天OCR与不使用聊天布局过滤的文档OCR模式。
- `src/lexiaodu/knowledge.py`：整理层 BM25、审核原文 FTS5、受众隔离和两层统一排序；文档名、章节、精确短语和正文共同参与排序。
- `config/app.toml`：默认来源目录、审核暂存目录和本地知识路径。
- `tests/test_generator.py`、`tests/test_risk.py`、`tests/test_feedback.py`：Day 4 核心逻辑测试。
- `tests/test_chat.py`、`tests/test_workflow.py`：工作台和悬浮工具端到端交互回归。
- `tests/test_knowledge_import.py`：格式提取、链接规范化、逐块审核、冲突/低可信阻断、版本切换、来源缺失、增量草稿、暂停恢复和链接入库测试。

## 验证命令

```powershell
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider --basetemp artifacts\pytest-final-push
.\.venv\python.exe -m compileall -q src tests scripts
.\.venv\python.exe -m pip check
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\python.exe -B scripts\verify_day5_queries.py
.\.venv\python.exe -B scripts\verify_doubao.py
.\.venv\python.exe -B -m lexiaodu --knowledge-link-report
git diff --check
```

2026-08-04 双层知识库最终结果：

- 完整测试：99 tests passed（最终复测 6.06 秒）。
- Python 编译检查：通过；依赖一致性：`No broken requirements found`。
- 真实覆盖报告：16 个来源、16 个审核修订、1,908 个内容块、213,676 个原文字符、192,682 个顾问可检索字符；473 个图片对象中 467 个 OCR 有文字、6 个无文字，失败 0 个、阻断 4 个。
- 真实链接报告：96 次引用、89 个唯一资料、5 个已入库且顾问可用、84 个未入库。
- 数据隔离检查：`顾问聊天记录` 来源 0 个，原文检索切片中的 URL 0 个，FTS5 正式切片 2,020 个。
- 代表性图片检索和内部审计开关通过；Windows 控制台特殊 OCR 符号不再导致编码异常。
- 差异空白检查通过，仅有仓库既有 LF/CRLF 转换提示。
- 删除双层迁移前临时数据库备份、测试临时目录和本次编译缓存；两个已应用审核批次及其报告继续保留以便追溯。

2026-08-03 最终结果：

- 完整测试：87 tests passed。
- Python 编译检查：通过。
- 依赖一致性：`No broken requirements found`。
- 四组固定查询全部通过，目标资料均排名第 1。
- 真实豆包鉴权、指定模型调用和 JSON 结构化输出通过；本次耗时 8.81 秒，虚构测试内容的顾虑摘要与微信回复均非空。
- 真实链接报告：96次引用、89个唯一资料、5个已入库、84个未入库。
- 差异空白检查：通过；仅有 Git 的 LF/CRLF 工作区提示。
- 截图选区定时测试为80ms产品延迟保留250ms测试等待窗口，避免Windows定时调度抖动；产品行为未改变。

## 已知边界与后续工作

- 豆包生成依赖网络、方舟服务可用性、账户额度和模型权限；失败时显示生成错误，不会自动绕过本地风险规则。
- 启用豆包会把本次 OCR 校正对话和本次两层知识检索片段发送给火山方舟；正式使用前仍需确认供应商数据处理要求。
- 风险规则是保守的确定性关键词规则；新业务风险类型需要显式补规则和测试。
- 通过审核导入命令应用知识时会自动重建索引；直接手工编辑 `knowledge/` 后仍需执行 `--rebuild-knowledge`。
- 增量来源导入支持扫描PDF OCR；直接把扫描PDF放入正式 `knowledge/` 仍不能由基础索引器OCR。
- 旧版 `.doc`、`.xls`、`.ppt` 不直接提取，会进入转换清单，需先转换为对应 OOXML 格式。
- 知识草稿必须经人工或Codex审核；提取失败、时期待确认、事实冲突和仅标题相似的链接不能自动进入正式知识。
- 内部链接只记录在本地元数据和审核报告中，导入器不会自动访问或下载。
- 聊天和建议历史仅驻留当前进程；只有结构化反馈会持久化。
