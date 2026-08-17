from pathlib import Path

import pytest
from dotenv import dotenv_values

from lexiaodu.runtime import configure_diagnostics, diagnostic_text, record_error
from tools.build_windows_release import (
    RUNTIME_KEYS,
    conda_openssl_binaries,
    read_runtime_values,
    validate_app_tree,
    write_runtime_env,
)


def test_release_environment_is_filtered_and_keeps_literal_values(tmp_path: Path) -> None:
    source = tmp_path / ".env"
    source.write_text(
        "\n".join(
            (
                "ARK_MODEL=model",
                "ARK_API_KEY=secret-${LITERAL}",
                "VOLC_ACCESSKEY=access",
                "VOLC_SECRETKEY=knowledge-secret",
                "ARK_KB_COLLECTION=documents",
                "TOS_BUCKET=must-not-ship",
            )
        ),
        encoding="utf-8",
    )

    values = read_runtime_values(source)
    bundled = tmp_path / "runtime.env"
    write_runtime_env(bundled, values)
    parsed = dotenv_values(bundled, interpolate=False)

    assert tuple(values) == RUNTIME_KEYS
    assert set(parsed) == set(RUNTIME_KEYS)
    assert parsed["ARK_API_KEY"] == "secret-${LITERAL}"
    assert "TOS" not in bundled.read_text(encoding="utf-8")


def test_release_environment_requires_real_service_configuration(tmp_path: Path) -> None:
    source = tmp_path / ".env"
    source.write_text("ARK_MODEL=model\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ARK_API_KEY"):
        read_runtime_values(source)


def test_packaged_tree_rejects_source_and_development_data(tmp_path: Path) -> None:
    app = tmp_path / "Lexiaodu"
    app.mkdir()
    (app / "Lexiaodu.exe").write_bytes(b"exe")
    (app / "runtime.env").write_text("ARK_MODEL=model", encoding="utf-8")
    validate_app_tree(app)

    (app / "leak.py").write_text("secret = True", encoding="utf-8")
    with pytest.raises(RuntimeError, match="leak.py"):
        validate_app_tree(app)


def test_conda_openssl_binaries_are_collected_when_present(tmp_path: Path) -> None:
    library_bin = tmp_path / "Library" / "bin"
    library_bin.mkdir(parents=True)
    crypto = library_bin / "libcrypto-3-x64.dll"
    ssl = library_bin / "libssl-3-x64.dll"
    crypto.touch()
    ssl.touch()

    assert conda_openssl_binaries(tmp_path) == (crypto, ssl)


def test_diagnostics_log_only_error_type(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    configure_diagnostics(log_dir)

    record_error("生成回复", RuntimeError("secret-token 家长正文"))

    copied = diagnostic_text()
    logged = (log_dir / "lexiaodu.log").read_text(encoding="utf-8")
    assert "RuntimeError" in copied
    assert "RuntimeError" in logged
    assert "secret-token" not in copied + logged
    assert "家长正文" not in copied + logged


def test_nsis_installer_is_current_user_and_preserves_user_data() -> None:
    script = Path("installer/lexiaodu.nsi").read_text(encoding="utf-8")

    assert "RequestExecutionLevel user" in script
    assert r'InstallDir "$LOCALAPPDATA\Programs\Lexiaodu"' in script
    assert r'$SMPROGRAMS\乐小读' in script
    assert r'$DESKTOP\乐小读.lnk' in script
    assert r'RMDir /r "$INSTDIR"' in script
    assert r'$LOCALAPPDATA\Lexiaodu' not in script


def test_one_page_guide_source_matches_installer_flow() -> None:
    guide = Path("installer/user-guide.html").read_text(encoding="utf-8")

    assert "更多信息" in guide
    assert "仍要运行" in guide
    assert "桌面或开始菜单" in guide
    assert "复制诊断信息" in guide
