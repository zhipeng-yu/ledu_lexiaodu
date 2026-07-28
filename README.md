# 乐小读

“乐小读”五日 MVP 的 Day 1 工程骨架。目前只包含配置、领域数据、虚构演示资料、置顶悬浮工具条和单屏区域截图验证；OCR、文本处理和阅读反馈等 Day 2–5 功能尚未实现。

## 环境

项目固定使用 Python 3.11，并将环境放在仓库内的 `.venv`。在 PowerShell 中从项目根目录执行：

```powershell
$env:CONDA_PKGS_DIRS = 'E:\DevCaches\conda-pkgs'
conda --no-plugins create --prefix .\.venv --solver classic python=3.11 pip -y
$env:PIP_CACHE_DIR = 'E:\DevCaches\pip'
.\.venv\python.exe -m pip install -e ".[dev]"
```

这些命令不会安装依赖到 Conda base。

## 运行

启动置顶悬浮工具条：

```powershell
.\.venv\python.exe -m lexiaodu
```

执行一次主屏幕中央区域截图烟测（输出目录已被 Git 忽略）：

```powershell
.\.venv\python.exe -m lexiaodu --capture-smoke artifacts\day1-smoke.png
```

运行测试：

```powershell
.\.venv\python.exe -m pytest
```

截图坐标使用 Qt 的逻辑像素，并且必须完整落在同一个屏幕内。跨屏区域会被明确拒绝，不会被静默裁剪或拼接。
