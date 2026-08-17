from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
RELEASE = ROOT / "release"
RUNTIME_KEYS = (
    "LEXIAODU_GENERATOR",
    "ARK_BASE_URL",
    "ARK_MODEL",
    "ARK_API_KEY",
    "VOLC_ACCESSKEY",
    "VOLC_SECRETKEY",
    "VOLC_REGION",
    "ARK_KB_COLLECTION",
    "ARK_KB_PROJECT",
    "ARK_KB_HOST",
)
RUNTIME_DEFAULTS = {
    "LEXIAODU_GENERATOR": "doubao",
    "ARK_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
    "VOLC_REGION": "cn-beijing",
    "ARK_KB_PROJECT": "default",
    "ARK_KB_HOST": "api-knowledgebase.mlp.cn-beijing.volces.com",
}
REQUIRED_KEYS = (
    "ARK_MODEL",
    "ARK_API_KEY",
    "VOLC_ACCESSKEY",
    "VOLC_SECRETKEY",
    "ARK_KB_COLLECTION",
)


def read_runtime_values(env_path: Path) -> dict[str, str]:
    raw = dotenv_values(env_path, interpolate=False)
    values = {
        key: str(raw.get(key) or RUNTIME_DEFAULTS.get(key, "")).strip()
        for key in RUNTIME_KEYS
    }
    if values["LEXIAODU_GENERATOR"].casefold() != "doubao":
        raise ValueError("发布构建要求 LEXIAODU_GENERATOR=doubao")
    missing = [key for key in REQUIRED_KEYS if not values[key]]
    if missing:
        raise ValueError("私密 .env 缺少发布配置：" + "、".join(missing))
    return values


def write_runtime_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(
            f"{key}={json.dumps(values[key], ensure_ascii=False)}\n"
            for key in RUNTIME_KEYS
        ),
        encoding="utf-8",
    )


def find_makensis() -> Path:
    configured = os.environ.get("MAKENSIS_PATH")
    command = shutil.which("makensis")
    candidates = tuple(
        Path(value)
        for value in (
            configured,
            command,
            r"E:\Program\NSIS\makensis.exe",
            r"D:\Program\NSIS\makensis.exe",
            r"C:\Program Files (x86)\NSIS\makensis.exe",
            r"C:\Program Files\NSIS\makensis.exe",
        )
        if value
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到 NSIS 编译器 makensis.exe")


def validate_app_tree(app_dir: Path) -> None:
    paths = tuple(
        path.relative_to(app_dir)
        for path in app_dir.rglob("*")
        if path.is_file()
    )
    forbidden_names = {".env", ".venv", "tests", "data", "__pycache__"}
    invalid = [
        path
        for path in paths
        if path.suffix.casefold() == ".py"
        or any(part.casefold() in forbidden_names for part in path.parts)
    ]
    if invalid:
        raise RuntimeError("应用目录包含禁止发布的文件：" + "、".join(map(str, invalid)))
    if not (app_dir / "Lexiaodu.exe").is_file():
        raise RuntimeError("PyInstaller 未生成 Lexiaodu.exe")


def project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(project["project"]["version"])


def conda_openssl_binaries(prefix: Path = Path(sys.prefix)) -> tuple[Path, ...]:
    library_bin = prefix / "Library" / "bin"
    return tuple(
        sorted(library_bin.glob("libcrypto-*.dll"))
        + sorted(library_bin.glob("libssl-*.dll"))
    )


def render_manual(output_path: Path) -> Path:
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import (
        QFont,
        QImage,
        QPageLayout,
        QPageSize,
        QPainter,
        QPdfWriter,
        QTextDocument,
    )
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    width, height = 1240, 1754
    margin_x, margin_y = 106, 94
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.setDotsPerMeterX(5906)
    image.setDotsPerMeterY(5906)
    image.fill("white")
    document = QTextDocument()
    document.setDefaultFont(QFont("Microsoft YaHei", 11))
    document.setHtml(
        (ROOT / "installer" / "user-guide.html").read_text(encoding="utf-8")
    )
    content_size = QSizeF(width - 2 * margin_x, height - 2 * margin_y)
    document.setPageSize(content_size)
    if document.size().height() > content_size.height():
        raise RuntimeError("使用说明内容超过一页")
    painter = QPainter(image)
    painter.translate(margin_x, margin_y)
    document.drawContents(
        painter,
        QRectF(0, 0, content_size.width(), content_size.height()),
    )
    painter.end()

    writer = QPdfWriter(str(output_path))
    writer.setResolution(150)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setTitle("乐小读使用说明")
    painter = QPainter(writer)
    painter.drawImage(QRectF(0, 0, writer.width(), writer.height()), image)
    painter.end()
    application.processEvents()

    pdf = QPdfDocument()
    pdf.load(str(output_path))
    if pdf.pageCount() != 1:
        raise RuntimeError(f"使用说明必须为一页，实际为 {pdf.pageCount()} 页")
    preview = ARTIFACTS / "manual-preview.png"
    if not image.save(str(preview), "PNG"):
        raise RuntimeError("无法渲染使用说明预览")
    return preview


def build() -> tuple[Path, Path]:
    if sys.platform != "win32":
        raise RuntimeError("Windows 安装包只能在 Windows 上构建")
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError('请先运行 .\\.venv\\python.exe -m pip install -e ".[build]"')

    values = read_runtime_values(ROOT / ".env")
    app_parent = ARTIFACTS / "windows-app"
    app_dir = app_parent / "Lexiaodu"
    pyinstaller_work = ARTIFACTS / "pyinstaller"
    RELEASE.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=ARTIFACTS) as temporary_dir:
        runtime_env = Path(temporary_dir) / "runtime.env"
        write_runtime_env(runtime_env, values)
        pyinstaller_command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--windowed",
            "--onedir",
            "--noupx",
            "--name",
            "Lexiaodu",
            "--paths",
            str(ROOT / "src"),
            "--distpath",
            str(app_parent),
            "--workpath",
            str(pyinstaller_work / "work"),
            "--specpath",
            str(pyinstaller_work),
            "--add-data",
            f"{ROOT / 'config' / 'app.toml'}{os.pathsep}config",
            "--add-data",
            f"{runtime_env}{os.pathsep}.",
        ]
        for library in conda_openssl_binaries():
            pyinstaller_command.extend(
                ("--add-binary", f"{library}{os.pathsep}.")
            )
        pyinstaller_command.append(
            str(ROOT / "src" / "lexiaodu" / "__main__.py")
        )
        subprocess.run(
            pyinstaller_command,
            cwd=ROOT,
            check=True,
        )

    validate_app_tree(app_dir)
    manual = RELEASE / "使用说明.pdf"
    manual.unlink(missing_ok=True)
    render_manual(manual)
    if not manual.is_file():
        raise RuntimeError("未生成使用说明 PDF")

    version = project_version()
    file_version = ".".join((version.split(".") + ["0", "0", "0"])[:4])
    subprocess.run(
        [
            str(find_makensis()),
            "/INPUTCHARSET",
            "UTF8",
            f"/DAPP_SOURCE={app_dir}",
            f"/DOUTPUT_DIR={RELEASE}",
            f"/DAPP_VERSION={version}",
            f"/DAPP_FILE_VERSION={file_version}",
            str(ROOT / "installer" / "lexiaodu.nsi"),
        ],
        cwd=ROOT,
        check=True,
    )
    installer = RELEASE / f"Lexiaodu-Setup-{version}.exe"
    if not installer.is_file():
        raise RuntimeError("NSIS 未生成安装包")
    return installer, manual


if __name__ == "__main__":
    setup, guide = build()
    print(f"安装包：{setup}")
    print(f"使用说明：{guide}")
