from pathlib import Path

from lexiaodu.app import _console_safe_text, run


def _write_config(path: Path, root: Path, database: Path) -> None:
    path.write_text(
        (
            "[knowledge]\n"
            f'root_dir = "{root.as_posix()}"\n'
            f'database_path = "{database.as_posix()}"\n'
        ),
        encoding="utf-8",
    )


def test_rebuild_and_search_cli_shows_source_and_evidence(
    tmp_path: Path, capsys
) -> None:
    root = tmp_path / "knowledge"
    policy = root / "policy"
    policy.mkdir(parents=True)
    (root / "style_case").mkdir()
    (policy / "夜航规则.txt").write_text(
        "# 罗盘章\n夜航时必须启用萤火罗盘。",
        encoding="utf-8",
    )
    config = tmp_path / "app.toml"
    _write_config(config, root, tmp_path / "knowledge.sqlite3")

    exit_code = run(
        [
            "--config",
            str(config),
            "--rebuild-knowledge",
            "--search",
            "萤火罗盘",
            "--knowledge-type",
            "policy",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "知识索引重建完成" in output
    assert "夜航规则.txt" in output
    assert "罗盘章" in output
    assert "证据：夜航时必须启用萤火罗盘。" in output


def test_search_cli_requires_explicit_knowledge_type(
    tmp_path: Path, capsys
) -> None:
    config = tmp_path / "app.toml"
    _write_config(config, tmp_path / "knowledge", tmp_path / "knowledge.sqlite3")

    exit_code = run(["--config", str(config), "--search", "罗盘"])

    assert exit_code == 2
    assert "--knowledge-type" in capsys.readouterr().err


def test_coverage_cli_and_internal_flag_validation(
    tmp_path: Path, capsys
) -> None:
    config = tmp_path / "app.toml"
    _write_config(config, tmp_path / "knowledge", tmp_path / "knowledge.sqlite3")

    exit_code = run(
        ["--config", str(config), "--knowledge-coverage-report"]
    )

    assert exit_code == 0
    assert "来源 0 个" in capsys.readouterr().out
    invalid = run(
        [
            "--config",
            str(config),
            "--search",
            "课程",
            "--knowledge-type",
            "policy",
            "--include-internal",
        ]
    )
    assert invalid == 2
    assert "只能与 source 检索" in capsys.readouterr().err


def test_console_safe_text_replaces_unencodable_ocr_symbols() -> None:
    class AsciiStream:
        encoding = "ascii"

    assert _console_safe_text("course ⬆", AsciiStream()) == "course ?"
