# 乐小读

“乐小读”五日 MVP 的 Day 2 版本。悬浮工具可拖框截取聊天区域，在内存中调用本地 PaddleOCR，按文字左右位置初判家长/顾问，并打开校正窗口供用户编辑文字、调整发言人或手动粘贴内容。

## 环境

项目固定使用 Python 3.11，并将环境放在仓库内的 `.venv`。在 PowerShell 中从项目根目录执行：

```powershell
$env:CONDA_PKGS_DIRS = 'E:\DevCaches\conda-pkgs'
conda --no-plugins create --prefix .\.venv --solver classic python=3.11 pip -y
$env:PIP_CACHE_DIR = 'E:\DevCaches\pip'
.\.venv\python.exe -m pip install -e ".[dev,ocr]" --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

这些命令不会安装依赖到 Conda base。若仅需运行无 OCR 的手动粘贴兜底，可安装 `.[dev]`；应用会在 PaddleOCR 不可用时自动降级。

PaddleOCR 首次运行会下载 PP-OCRv5 mobile 检测和识别模型。默认模型缓存为 `E:\DevCaches\paddlex`，可在 `config/app.toml` 的 `ocr.model_cache_dir` 中修改。

## 运行

启动置顶悬浮工具条：

```powershell
.\.venv\python.exe -m lexiaodu
```

点击“框选截图”后拖动鼠标选择一个聊天区域：

1. 截图以 `QImage` 保留在当前进程内，不保存图片或临时文件。
2. PaddleOCR 直接接收内存像素数组。
3. 文字框中心在画面左半边时初判为“家长”，右半边时初判为“顾问”。
4. 在 OCR 校正窗口中可编辑文字和发言人；OCR 不可用或遗漏时，可粘贴文字并指定发言人。

执行一次主屏幕中央区域的纯内存截图烟测：

```powershell
.\.venv\python.exe -m lexiaodu --capture-smoke
```

运行测试：

```powershell
.\.venv\python.exe -m pytest
```

截图坐标使用 Qt 的逻辑像素，并且必须完整落在同一个屏幕内。跨屏区域会被明确拒绝，不会被静默裁剪或拼接。

## 隐私与缓存

- 聊天截图不会写入磁盘，也没有截图历史记录。
- OCR 模型权重是可复用开发缓存，不包含用户截图。
- PaddlePaddle 3.2 在 Windows 导入时会创建一个很小的 `%USERPROFILE%\.cache\paddle\dataset` 目录；模型权重仍使用上述 E 盘缓存。
- 当前校正结果只驻留在校正窗口中，尚未接入 Day 3 后续流程或持久化。
