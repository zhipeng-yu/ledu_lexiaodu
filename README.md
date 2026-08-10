# 乐小读

> 2026-08-10 当前版本：以豆包为主体的独立顾问聊天应用。公司原文档放入 `company_documents/`，顾问直接提问，AI 自动选择最多三份相关文件；PDF 以原始字节临时上传方舟。本地不再运行知识库、OCR、截图附件、文本切段、回复卡或旧反馈流程。

## 当前使用方式

```powershell
.\.venv\python.exe -m lexiaodu
```

`.env` 需配置 `LEXIAODU_GENERATOR=doubao`、`ARK_BASE_URL`、`ARK_MODEL` 和 `ARK_API_KEY`。只有显式设置 `LEXIAODU_GENERATOR=simulated` 才进入离线演示。

- PDF：可以自动选择并以原文件上传方舟回答。
- DOCX、PPTX、XLSX：可以发现和选择，但读取正文仍需接通方舟文档知识库。
- 会话和消息使用本地加密保存并严格按会话隔离；发送给豆包的历史明确标注“顾问”和“乐小读”。
- 公司事实无原文依据时必须说明待核实；实时业务状态必须查询业务系统；高风险事项必须人工核实。
- 应用不会直接向家长发送消息，最终使用权属于顾问。

当前尚未完成：Office 文档知识库接入、真实页码/章节引用稳定性验收、脱敏且人工审核的优秀顾问样例学习闭环。

---

## 历史归档（以下流程已失效，不可作为当前运行说明）

## 交付导航

- [安装与运行](#环境)
- [五分钟演示脚本](docs/DEMO_SCRIPT.md)
- [指定电脑手动测试清单](docs/MANUAL_TEST_CHECKLIST.md)
- [顾问试用记录表](docs/ADVISOR_TRIAL_FORM.md)
- [Day 5 验收结果](docs/ACCEPTANCE_RESULTS.md)

## 当前知识审核状态

- 最终 source 重审批次：`20260806T081640Z-d53c041b`；policy 升级批次：`20260806T082119Z-d42bb304`。两个 source 重审批次均复用既有修订、原文块和OCR缓存，`extracted/` 为0。
- 业务已确认不保留任何活动：1,259 条活动候选、252 个独立活动组全部舍弃，活动查询不返回事实；活动、续报营销和内部话术原文不能从 SOURCE 检索旁路召回。
- 全国班、文综等资料已确认适用于天津；稳定公开课程事实按块放行，备课、师训、考核、排课、绩效、内部话术和触达执行不进入顾问检索。
- 稳定续报规则继续作为事实；脱敏续报沟通只作为 style case。当前优惠、赠品和截止时间没有正式活动证据时返回0条事实。
- 正式可用 semantic 14,818 条，source 绑定率 100%；policy 22 份、308 章、358 条有效映射，章节和间接 source 绑定率均为 100%。审核教师共11位：原有谢云琦、孟玮娜、卢明浩，并新增何强、杨晓宁、张晨、韩剑、王萌、郭娜、吴凡、陆沪杰。正文与嵌入介绍图冲突的精确教学年限和带班轮次继续阻断。

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

### 豆包 API 验证配置

复制配置模板并只在本机填写方舟模型推理 API Key：

```powershell
Copy-Item .env.example .env
notepad .env
```

运行独立验证脚本时 `.env` 应为：

```dotenv
LEXIAODU_GENERATOR=doubao
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=doubao-seed-2-0-lite-260215
ARK_API_KEY=替换为方舟模型推理APIKey
```

`.env` 已被 Git 忽略。不要填写 Access Key ID、Secret Access Key、`Bearer` 前缀或 Coding Plan Key，也不要提交、打印或发送真实 Key。以下命令只验证豆包鉴权、模型调用和结构化输出（使用虚构内容，会产生少量 Token 费用），不会把豆包接入独立聊天窗口：

```powershell
.\.venv\python.exe -B scripts\verify_doubao.py
```

## 运行

默认启动独立聊天窗口：

```powershell
.\.venv\python.exe -m lexiaodu
```

窗口支持新建、选择、重命名、搜索和删除本地会话。把公司原始 `PDF`、`DOCX`、`PPTX`、`XLSX` 文件放入项目的 `company_documents/` 目录后，顾问只需直接提问；乐小读会根据会话内容自动选择最多三份相关原文档。选中的 PDF 会以原始字节上传方舟并参与回答，不在本地执行 OCR 或文本切段。DOCX、PPTX 和 XLSX 已纳入自动选择，但必须在接通方舟文档知识库接口后才能读取，未接通时会明确提示而不会编造。

聊天界面不再提供截图、粘贴截图或 OCR 功能。

## Generator 验证组件

仓库保留了厂商无关的 `Generator.generate(GenerationRequest)` 组件，用于豆包能力验证和后续原文档顾问接入：

- `SimulatedGenerator` 是测试旧建议服务边界的确定性实现。
- `OpenAICompatibleGenerator` 可由 `scripts/verify_doubao.py` 装配火山方舟 OpenAI 兼容 Chat API，并限制输出长度、关闭深度思考。
- 若后续 API 不是 OpenAI 兼容协议，只需新增一个实现 `Generator` 的适配器。

验证脚本通过 `python-dotenv` 读取本机 `.env`，再通过 OpenAI SDK 调用方舟；真实密钥不会进入 Git。当前独立聊天启动路径固定使用 `OfflineDemoAssistant`，即使 `.env` 配置了豆包也不会改变这一点；生产原文档顾问将在后续任务中接入。

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

- 最新正式 source 重审批次为 `20260806T081640Z-d53c041b`。92 份正式修订均复用既有 source blocks 和 OCR 缓存，批次 `extracted/` 为0；另有1个 Office 临时锁文件被排除，不形成正式修订。
- 原3,210个待核对块累计终态为 advisor 1,393、pending/blocked 1,026、discarded 791、no_text 0、failed 0。全量块处置为 advisor 9,980、internal 20、pending 1,026、discarded 12,376、no_text 1,131、failed 19；没有批量放行。
- 39,814条 semantic 候选全部完成审核决定：14,818 `approved`、3,761 `deferred`、21,235 `discarded`、0 `pending`；正式可用 semantic 为14,818条，source绑定率100%。
- 1,259条活动候选和归并后的252个独立活动组全部为 `discarded`；active、expired、pending、conflict均为0，活动查询不返回事实。
- `文综教师介绍.docx` 经业务确认是当前天津正式对外资料。字段级审核新增何强、杨晓宁、张晨、韩剑、王萌、郭娜、吴凡、陆沪杰8位教师；48个公开块获准、2个精确值冲突块继续阻断、34个混合内部/效果/营销块舍弃、8个无文字。审核教师现共11位。
- policy 升级批次为 `20260806T082119Z-d42bb304`；正式 policy 保持22份，增至308章、358条有效semantic映射，4份 `style_case` 事实边界未变；`policy +0.08` 和 `primary +0.03` 保持不变。老师私人联系方式、员工/学员标识符及真实学员个案请求在顾问链路中直接不进入 RAG。

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

## 隐私与缓存

- 默认聊天历史使用应用层 AES-GCM 加密后写入 `data/chat.sqlite3`；标题、消息、OCR 校正文案、回复卡业务内容和附件路径不会以明文保存。附件内容使用独立随机数据密钥加密并以随机 `.bin` 文件保存在 `data/chat-attachments`。
- 本地主密钥由当前 Windows 用户范围的 DPAPI 保护。项目不提供云备份或跨设备密钥恢复；Windows 用户配置或受保护密钥丢失时，本地历史可能无法恢复。
- 当前数据边界是 Windows 账号，不是应用内账号。同一 Windows 账号下的所有使用者可以看到同一份本地会话；共享电脑应为不同顾问使用不同 Windows 账号。
- 豆包回答时，当前会话上下文及自动选中的公司原文档会发送给方舟；正式使用前必须确认业务隐私与供应商数据处理要求。
- `data/feedback.sqlite3` 仅保存建议 ID、有用状态、枚举原因和时间戳，表结构中没有聊天、问题或回复正文字段；独立聊天在生产反馈存储接入前不显示回复卡反馈控件。
- 确定性高风险规则覆盖退款/投诉/法律争议、人身安全/健康、隐私和儿童保护；没有权威制度检索结果时也按高风险处理并要求转人工。

## 已知限制

- 豆包生成依赖网络、方舟服务可用性、账户额度和模型权限；失败时界面会显示生成错误，不会自动绕过风险规则。
- PDF 可直接以原文件参与回答；DOCX、PPTX、XLSX 仍需接通方舟文档知识库后才能读取正文。
- 自动选文档目前依据会话、文件名和相对目录判断，建议使用能说明内容的文件名和目录名。
- 独立聊天会恢复本地加密的会话、消息和既有回复卡。
- DPAPI 保护意味着本地聊天历史不能直接迁移到另一台电脑或另一个 Windows 账号；当前版本没有密钥恢复流程。
