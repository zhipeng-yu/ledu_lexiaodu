# 乐小读 Day 3 Handoff

更新时间：2026-07-30

## 开始门槛

- 开始时当前分支为 `agent/fix-chat-ocr-false-positives`，`HEAD` 为 `60ec1ca`（`Fix chat OCR false positives`）。
- 已确认 Day 2 提交 `0be7638`（`feat: implement Day 2 capture and OCR workflow`）是当前 `HEAD` 的祖先。
- 开始时工作区无未提交改动；Day 2 基线测试为 25 tests passed。

## 完成范围

- 支持导入 UTF-8 TXT、DOCX 和文本型 PDF；扫描型 PDF 会明确拒绝，不会静默建立空索引。
- TXT 与 DOCX 按标题/Heading 段落记录章节，PDF 按页记录页码。
- 章节或页面正文按句子边界切分，单个切片最长 500 字符。
- 使用本地 SQLite 保存文档路径、名称、知识类型、格式、大小、修改时间、索引时间，以及切片顺序、章节/页码和正文。
- 实现本地 BM25 检索；中文使用单字和双字组合分词，英文和数字按词分词。
- 单次检索最多返回 Top 3，并展示知识类型、文档名、章节或页码、证据片段。
- 知识目录强制使用 `policy/` 和 `style_case/` 两个分类子目录；未分类的受支持文档会阻止重建。
- 每次检索必须显式指定 `policy` 或 `style_case`，SQL 查询只加载选定分类，权威知识和风格案例不会混排。
- 实现全量目录重建；解析先于 SQLite 替换，成功后清除已删除文档留下的旧索引。
- 新增命令行重建与检索入口，并补充虚构的月莓学院、星舟、云鲸等测试资料。

## 使用方式

知识目录结构：

```text
knowledge/
├── policy/
└── style_case/
```

重建索引：

```powershell
.\.venv\python.exe -m lexiaodu --rebuild-knowledge
```

检索权威知识：

```powershell
.\.venv\python.exe -m lexiaodu --search "请假流程" --knowledge-type policy
```

检索风格案例：

```powershell
.\.venv\python.exe -m lexiaodu --search "如何温和表达" --knowledge-type style_case
```

也可组合 `--rebuild-knowledge` 与 `--search`，在重建后立即检索。

## 主要文件

- `src/lexiaodu/knowledge.py`：格式解析、来源定位、文档切分、SQLite 重建、BM25 和结果展示。
- `src/lexiaodu/app.py`：`--rebuild-knowledge`、`--search`、`--knowledge-type` 命令行入口。
- `src/lexiaodu/config.py` / `config/app.toml`：知识目录和 SQLite 路径设置。
- `pyproject.toml`：新增 `pypdf>=5,<7` 运行依赖。
- `tests/test_knowledge.py`：三种格式、切分、元数据、Top 3、分类隔离和重建测试。
- `tests/test_knowledge_cli.py`：命令行来源展示和显式分类要求测试。
- `README.md`：Day 3 目录约定、重建及检索说明。

## 验证结果

- `.\.venv\python.exe -m pytest -q`：33 tests passed。
- `.\.venv\python.exe -m compileall -q src tests`：通过。
- `.\.venv\python.exe -m pip check`：No broken requirements found。
- PDF 回归测试使用测试期间生成的最小文本型 PDF，确认 `pypdf` 实际提取第一页文本。
- DOCX 回归测试使用测试期间生成的标准 `word/document.xml`，确认 Heading 章节来源。
- 重建回归确认删除旧源文件后，旧文档与旧切片不会残留在 SQLite。

## 已知边界

- PDF 仅支持自带文本层的文件；扫描型 PDF 没有接入 OCR。
- TXT 仅接受 UTF-8/UTF-8 BOM；DOCX 章节优先识别 Word Heading 样式和常见中文章节标题。
- 当前 BM25 是关键词检索，不提供同义词或向量语义召回。
- 当前仅提供全量重建，没有文件监听或增量索引。
- OCR 校正结果尚未自动触发知识检索；Day 4 可调用 `KnowledgeBase.search()` 接入后续建议流程。
- Day 2 的固定左右气泡过滤、单屏框选和 OCR 主线程加载等既有边界未改变。

## 后续可复用接口

- `KnowledgeBase(root_dir, database_path).rebuild()`：从本地分类目录全量重建 SQLite。
- `KnowledgeBase.search(query, KnowledgeType.POLICY)`：检索权威知识，最多返回 3 条。
- `KnowledgeBase.search(query, KnowledgeType.STYLE_CASE)`：检索风格案例，最多返回 3 条。
- `SearchResult`：提供 `document_name`、`locator`、`evidence`、`score` 和 `knowledge_type`。
- `format_search_results()`：生成带文档名、章节/页码和证据片段的本地展示文本。
