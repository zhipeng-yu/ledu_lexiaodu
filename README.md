# 乐小读五日 MVP

Day 5 最终集成版覆盖完整顾问流程：截图或粘贴、OCR 校正、本地检索、豆包结构化建议、风险确认、编辑复制和匿名结构化反馈。配置方舟 API Key 后使用真实豆包模型；未启用时仍可使用本地确定性生成器。事实依据来自整理知识与审核原文的统一排序，风险等级由本地规则决定。

## 交付导航

- [安装与运行](#环境)
- [五分钟演示脚本](docs/DEMO_SCRIPT.md)
- [指定电脑手动测试清单](docs/MANUAL_TEST_CHECKLIST.md)
- [顾问试用记录表](docs/ADVISOR_TRIAL_FORM.md)
- [Day 5 验收结果](docs/ACCEPTANCE_RESULTS.md)

## 当前知识审核状态

- 最终 source 重审批次：`20260806T072331Z-efd0228e`；未创建新的 policy 升级批次。
- 业务已确认不保留任何活动：1,259 条活动候选、252 个独立活动组全部舍弃，活动查询不返回事实；活动、续报营销和内部话术原文不能从 SOURCE 检索旁路召回。
- 全国班、文综等资料已确认适用于天津；仅地域受阻的内容已放行，混有内部执行或其他待核对内容的块继续阻断。
- 正式可用 semantic 13,725 条，source 绑定率 100%；policy 22 份、300 章、319 条有效映射，章节和间接 source 绑定率均为 100%。审核教师仍为谢云琦、孟玮娜、卢明浩。

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

`knowledge/`、`data/` 和 `artifacts/` 按隐私策略不提交 Git。新电脑必须先从经审核的本地资料准备 `knowledge/policy` 与 `knowledge/style_case`，再执行下文的 `--rebuild-knowledge`；不要用真实聊天截图作为安装样例。

### 豆包 API 配置

复制配置模板并只在本机填写方舟模型推理 API Key：

```powershell
Copy-Item .env.example .env
notepad .env
```

启用豆包时 `.env` 应为：

```dotenv
LEXIAODU_GENERATOR=doubao
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-lite-260215
ARK_API_KEY=替换为方舟模型推理APIKey
```

`.env` 已被 Git 忽略。不要填写 Access Key ID、Secret Access Key、`Bearer` 前缀或 Coding Plan Key，也不要提交、打印或发送真实 Key。验证配置与真实结构化调用（使用虚构内容，会产生少量 Token 费用）：

```powershell
.\.venv\python.exe -B scripts\verify_doubao.py
```

## 运行

启动置顶悬浮工具条：

```powershell
.\.venv\python.exe -m lexiaodu
```

若只安装了 `.[dev]`，仍可使用 OCR 校正窗口的手动粘贴兜底；完整截图 OCR 演示需要安装 `.[dev,ocr]`。

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
2. 每次发送都会检索整理后的 `policy`、审核原文兜底和 `style_case`，再把真实结果交给 `.env` 选择的豆包或本地模拟生成器。
3. 建议卡包含顾虑摘要、可编辑微信短回复、带文档和章节定位的事实依据、风险提示及转人工状态。
4. 低、中风险建议可一键复制编辑后的短回复；高风险建议必须先勾选风险确认，复制按钮才会启用。
5. 可选择“有用”或“无用”并提交枚举原因。反馈数据库只记录建议 ID、选择、原因和时间，不保存聊天或回复正文。
6. Enter 发送，Shift+Enter 换行；窗口关闭后重新打开仍保留当前进程内的工作台记录，退出后不持久化聊天正文。

截图 OCR 识别完成后会先停留在校正窗口，建议服务此时不会启动。顾问核对文字和发言人并点击“确认无误并生成建议”后，应用才会打开独立的“顾问建议”结果窗口；该窗口不显示手动提问框，也不要求再次输入，直接执行检索、生成和风险流程。若知识索引尚未建立，结果窗口会明确提示生成失败；先执行 `--rebuild-knowledge` 即可。

## Generator 兼容层

业务流程只依赖 `Generator.generate(GenerationRequest)`，不依赖具体厂商 SDK：

- `SimulatedGenerator` 是无 Key 时可选的离线实现；有权威检索结果时，短回复直接使用排名第一的真实制度来源和证据，没有制度依据时只生成“转人工核实”回复。
- `OpenAICompatibleGenerator` 已装配火山方舟 OpenAI 兼容 Chat API。启用豆包时限制输出长度并关闭深度思考，以降低顾问回复的等待时间和费用。
- 若后续 API 不是 OpenAI 兼容协议，只需新增一个实现 `Generator` 的适配器。

程序通过 `python-dotenv` 读取本机 `.env`，通过 OpenAI SDK 调用方舟；真实密钥不会进入 Git。事实依据由应用直接绑定本地 `SearchResult`，不会采信模型生成的引用；风险等级也始终由本地确定性规则覆盖模型输出。

执行一次主屏幕中央区域的纯内存截图烟测：

```powershell
.\.venv\python.exe -m lexiaodu --capture-smoke
```

## 双层本地知识库与轻量语义层

知识库继续保留两层正式内容：`knowledge/` 保存便于顾问直接使用的整理知识，SQLite 保存可追溯的来源修订、完整提取内容、OCR、受众和审核状态。在两层之间增加轻量语义记录，追溯链固定为“审核 source block → semantic → policy”；它只做天津适用性过滤、课程/活动关系和原文候选补充，不替代原文或整理知识。原始 Word、PDF、图片等二进制文件继续留在配置的外部来源目录，不复制进仓库或数据库。

在配置的知识根目录下建立两个整理知识分类。支持继续在分类目录中建立更深层级，但可索引文档不能放在这两个分类之外：

```text
knowledge/
├── policy/       # 制度、产品规则等权威知识
└── style_case/   # 仅用于参考表达方式的案例
```

整理层支持 UTF-8 TXT、DOCX 和文本型 PDF；扫描型 PDF 应从下文的来源导入流程进入原文层。TXT 与 DOCX 按标题记录章节，PDF 按页记录页码，长内容切分为不超过 500 字符的切片。两层文档、切片、版本和来源元数据统一保存在本地 SQLite `data/knowledge.sqlite3` 中。

重建整个本地索引：

```powershell
.\.venv\python.exe -m lexiaodu --rebuild-knowledge
```

检索时必须显式选择知识类型，最多返回 3 条结果。每条结果包含文档名、章节或页码以及证据片段：

```powershell
.\.venv\python.exe -m lexiaodu --search "请假流程" --knowledge-type policy
.\.venv\python.exe -m lexiaodu --search "如何温和表达" --knowledge-type style_case
.\.venv\python.exe -m lexiaodu --search "初中数学 第1讲" --knowledge-type source
```

`source` 默认只查询“已审核、顾问可用、质量合格”的原文。仅在本机审计时才可增加 `--include-internal`；范围外、舍弃、待审核、低可信 OCR、冲突阻断块和链接 URL 不会传给回复生成器。顾问生成流程会合并整理后的 `policy` 与审核原文，相关度接近时优先整理知识，精确原文命中用于补足遗漏。问题明确写出年级、学科、班型、时期或教材时，正式语义记录先执行适用性过滤；召回阶段仍不增加语义分，整理知识 `+0.08` 与 primary `+0.03` 保持不变。

`style_case` 始终独立检索，只影响表达方式，不能映射为语义事实，也不能参与课程、价格、活动或服务事实竞争。App 课程显示、实时名额、订单和付款状态会标记为“需要查询实际系统”；生成器不会用 RAG 推断这些实时状态。

也可以先重建后立即检索：

```powershell
.\.venv\python.exe -m lexiaodu --rebuild-knowledge --search "请假流程" --knowledge-type policy
```

## 增量整理来源资料

### 当前人工复审基线（2026-08-06）

- 最新正式 source 重审批次为 `20260806T064138Z-4af31b4c`。92 份正式来源均为未变化文件，批次 `extracted/` 为 0 个文件，复用了既有 revision、source blocks 和 OCR 缓存；另有 1 个 Office 临时锁文件被排除，不形成正式修订。
- 原 3,210 个待核对块没有批量放行：0 个转为 advisor，3,210 个全部保持 `pending` 且质量标记为 `blocked`。连同既有 4 个事实风险块，质量阻断共 3,214 个。
- 39,814 条 semantic 候选已全部完成审核决定：13,135 `approved`、6,221 `deferred`、20,458 `discarded`、0 `pending`；正式可用 semantic 仍为 13,135 条，source 绑定率 100%。
- 1,259 条活动候选当前为 active 0、expired 0、pending 725、conflict 0、discarded 534。按活动类型、适用课程、时期和来源归并为 252 个独立证据分组：pending 122、discarded 130；没有任何材料满足完整日期、适用对象、条件、办理方式和权威来源门槛。
- 没有新增教师资料同时满足公开、脱敏、可核实和权威来源要求；审核教师仍只有谢云琦、孟玮娜、卢明浩。因无新增高频教师事实，本轮没有创建 policy 升级批次。
- 正式 policy 保持 22 份、300 章、319 条有效 semantic 映射，4 份 `style_case` 内容哈希未变；`policy +0.08` 和 `primary +0.03` 保持不变。老师私人联系方式、员工/学员标识符及真实学员个案请求在顾问链路中直接不进入 RAG。

来源资料目录、审核暂存目录和排除目录名由 `config/app.toml` 的
`knowledge_import.source_dir`、`knowledge_import.staging_dir`、
`knowledge_import.excluded_source_parts` 配置。来源目录递归支持 DOCX、XLSX、PPTX、
PDF、PNG、JPG/JPEG 和 WebP：Office 文档会提取正文、表格、页眉页脚、备注/批注、
链接、替代文字和嵌入图片 OCR；PDF 会提取文本、链接注释并对扫描页 OCR；独立图片
直接使用文档模式 OCR。`.doc`、`.xls`、`.ppt` 会进入转换清单，不会静默跳过。
默认排除 `顾问聊天记录/**`，由顾问语气学习任务单独处理，避免聊天截图成为产品事实。

将新资料放入来源目录后，先准备审核批次；此步骤不会修改正式知识文件或检索索引：

```powershell
.\.venv\python.exe -m lexiaodu --prepare-knowledge-import
```

每个批次会在暂存目录生成 `review.json`、`report.md` 和 `draft/knowledge/` 草稿。
完整提取结果在准备阶段写入待审核数据库修订；`review.json` 的
`raw.block_candidates` 会逐项列出稳定块 ID、定位、类型、预览、受众、质量、处置状态、天津适用建议、舍弃原因、OCR 置信度和警告，便于将对象明确归为顾问可用、内部留档、待核对、范围外/舍弃、无文字或提取失败。
审核时为每个变化来源填写 `outputs` 或 `excluded_reason`，并设置 `raw.status`、
`raw.audience`、`raw.authority`、`raw.usage_status`、`internal_locators` 和必要的 `block_overrides`；舍弃块必须填写 `discard_reason`，待核对数字或冲突块应将 `quality_status` 标为 `blocked`。`semantic.records` 中每条候选都绑定 source revision/block，审核决定只能是 `approved`、`blocked`、`discarded` 或 `deferred`；任何遗留 `pending`、篡改绑定或孤立事实都会阻止 apply。只有标题与稳定链接目标完全匹配时，
才把候选项加入 `aliases`。
建议输出路径会从文件名提取年份和季节；信息不足时标记“时期待确认”，不能直接应用。
若建议目标已有正式知识，准备阶段会复制一份到草稿区作为增量合并底稿，正式文件保持不变。
整理草稿不能未经审核覆盖正式知识；但审核通过且顾问可用的原文会进入原文兜底索引，
因此不会再因尚未整理成短知识块而丢失表格或图片信息。内部经营目标、人员、联系方式、排期、系统权限和无法核实的营销承诺会明确舍弃，不建设内部运营知识库。应用成功后会删除批次中的临时全文副本，只保留
审核文件、报告、批次元数据和数据库修订。

只调整审核处置、天津适用性或语义标签时，可复用已存 source blocks 创建重审批次；它仍会核对来源 SHA-256，但不会重新提取 Office/PDF 或重复 OCR：

```powershell
.\.venv\python.exe -m lexiaodu --prepare-knowledge-import --review-all-knowledge-sources
```

审核完成后应用批次并自动重建索引。apply 会先校验全部审核决定、来源绑定、活动日期、冲突和知识文件基线哈希，再在同一 SQLite 事务中切换 policy、source、semantic、映射和 FTS；任一步失败都会恢复知识文件并回滚数据库：

```powershell
.\.venv\python.exe -m lexiaodu --apply-knowledge-import <BATCH_ID>
```

随时查看链接引用和未入库资料数量：

```powershell
.\.venv\python.exe -m lexiaodu --knowledge-link-report
```

查看来源、内容块、字符、图片 OCR、无文字、失败和阻断项覆盖情况：

```powershell
.\.venv\python.exe -m lexiaodu --knowledge-coverage-report
```

查看语义候选/正式记录、来源绑定率、八大领域、关系、块处置和活动状态：

```powershell
.\.venv\python.exe -m lexiaodu --knowledge-semantic-report
```

### 从正式证据升级 Policy

需要把已审核的正式 `semantic/source` 提炼为高频整理知识时，使用 policy 升级模式：

```powershell
.\.venv\python.exe -m lexiaodu --prepare-knowledge-import --policy-upgrade
```

该模式只读取当前正式 SQLite，生成证据快照，并把当前 policy 与已有章节证据映射带入增量草稿和
`review.json` 的 `policy_upgrade` 审核区；首次没有 policy 时草稿为空。它不扫描原始资料、
不执行 OCR，也不修改正式检索。每个批准章节必须记录
唯一标题、正文哈希和至少一个有效 semantic record ID，系统会继续校验其 source revision/block、
天津适用范围、受众、质量、权威等级和活动状态。精确讲次、教材版本或价格还必须使用
`primary` 证据。

逐章审核完成后仍通过原有 apply 原子切换：

```powershell
.\.venv\python.exe -m lexiaodu --apply-knowledge-import <BATCH_ID>
```

policy-only apply 只替换 policy 文件、整理知识索引、章节级 semantic 映射和
`source_outputs`；正式 source、semantic 与四类 `style_case` 不会重建。失败时知识文件、
SQLite 映射和索引一起恢复。查看文件、章节、semantic/source 绑定率、领域覆盖和退休文件：

```powershell
.\.venv\python.exe -m lexiaodu --knowledge-policy-report
```

班型选择和教师背景/教学方式问题只使用审核后的 policy 结论，避免原始案例、员工信息或内部评价
参与事实回答；上海、广州等其他地区独有问题不会从天津知识库拼接答案。现有 `+0.08` policy
加分和 `+0.03` primary 加分保持不变。

活动只有日期完整、来源审核通过且 apply 当日处于有效期内才会标记为 `active`；`expired`、`pending`、`conflict` 均不能进入顾问检索。检索时还会根据当前日期再次检查，避免应用后自然过期的活动继续出现。

链接图按规范化 URL 去重，同时保留每次引用的来源和定位。报告区分已归档、顾问可用、
仅内部和未入库目标；导入器不自动访问或下载内部链接，URL 也不会进入顾问检索正文。

准备过程中按 Ctrl+C 可以暂停。已完成文件和 OCR 缓存会保留，之后从文件检查点继续：

```powershell
.\.venv\python.exe -m lexiaodu --resume-knowledge-import <BATCH_ID>
```

文件 SHA-256 用于识别新增、修改、重命名和未变化来源；未变化文件不会重复提取或
OCR。修改后的新修订在审核应用前不会替换旧正式版本；移走来源只会标记“来源缺失”，
旧审核版本仍可使用，不会自动删除已经审核的知识。

运行测试：

```powershell
.\.venv\python.exe -B -m pytest -q -p no:cacheprovider --basetemp artifacts\pytest-day5-final
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\python.exe -B scripts\verify_day5_queries.py
.\.venv\python.exe -B scripts\evaluate_advisor_knowledge.py
```

第二条命令使用当前 22 份 policy 结构验证四个固定查询；第三条命令运行 23 类匿名化顾问知识评测，检查实时系统、内部信息、隐私、活动和地区边界，并列出每题正式知识命中。完整演示步骤见 [演示脚本](docs/DEMO_SCRIPT.md)。

截图坐标使用 Qt 的逻辑像素，并且必须完整落在同一个屏幕内。跨屏区域会被明确拒绝，不会被静默裁剪或拼接。
当前 OCR 过滤针对固定的左右气泡布局；若真实消息可能出现在画面中央或紧贴最外侧，需要调整策略或人工粘贴校正。

## 隐私与缓存

- 聊天截图不会写入磁盘，也没有截图历史记录。
- 手动问题、OCR 对话和生成回复只保留在当前应用进程内，退出后不会写入磁盘。
- 启用豆包后，OCR 校正对话和本次检索片段会发送给火山方舟生成建议；本机不落盘不等于数据不出本机，正式使用前需确认业务隐私与供应商数据处理要求。
- `data/feedback.sqlite3` 仅保存建议 ID、有用状态、枚举原因和时间戳，表结构中没有聊天、问题或回复正文字段。
- OCR 模型权重是可复用开发缓存，不包含用户截图。
- 知识索引仅写入配置的本地 SQLite 文件；`policy`、`style_case` 与 `source` 在查询层强制分型，原文层额外执行审核状态、受众和质量隔离。
- PaddlePaddle 3.2 在 Windows 导入时会创建一个很小的 `%USERPROFILE%\.cache\paddle\dataset` 目录；模型权重仍使用上述 E 盘缓存。
- 确定性高风险规则覆盖退款/投诉/法律争议、人身安全/健康、隐私和儿童保护；没有权威制度检索结果时也按高风险处理并要求转人工。

## 已知限制

- 豆包生成依赖网络、方舟服务可用性、账户额度和模型权限；失败时界面会显示生成错误，不会自动绕过风险规则。
- OCR 过滤针对左右聊天气泡布局；中央消息、贴边消息、复杂引用卡片和特殊缩放可能需要人工校正或粘贴兜底。
- 截图区域必须完整位于一个屏幕，不能跨屏拼接。
- 知识正文和 SQLite 索引是本机数据，不随 Git 分发；换电脑后需要经审核导入并重建。
- 固定查询脚本针对当前 22 份 policy 结构；以后再次调整 policy 路径或文件名时应同步审核预期文件名。
- 聊天和建议历史只保留在当前进程；应用退出后不恢复，只有结构化反馈元数据会持久化。
- 最终演示电脑的真实屏幕缩放、剪贴板权限、Paddle 模型首次下载和真实聊天截图识别仍须按手动测试清单逐项确认。
