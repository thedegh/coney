# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for coney_tools.cli: exit codes and output of each command."""

import io
from pathlib import Path

import pytest

from coney_tools.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    """`--version` prints the package version and exits 0."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_config_show_lists_the_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "coney.local.example.toml").write_text("", encoding="utf-8")
    (tmp_path / "coney.local.toml").write_text('game_dir = "game"\n', encoding="utf-8")
    (tmp_path / "game").mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "game_dir" in out and "(found)" in out
    assert "jdk_home = unset" in out


def test_config_error_is_one_line_and_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "coney.local.example.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["config", "show"]) == 2
    err = capsys.readouterr().err
    assert "coney.local.toml" in err and "Traceback" not in err


def test_repo_check_fails_with_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "coney.local.example.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["repo", "check"]) == 1


def title_checkout(tmp_path: Path) -> Path:
    """A made-up checkout whose title rules allow only the area `docs` and the verb `Add`."""
    (tmp_path / "coney.local.example.toml").write_text("", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "commit-conventions.json").write_text(
        '{"areas": {"docs": "documentation"}, "verbs": ["Add"]}', encoding="utf-8"
    )
    return tmp_path


def test_check_title_passes_with_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(title_checkout(tmp_path))
    (tmp_path / "msg").write_text("# a comment\n\ndocs: Add the guide\n\nBody.\n", encoding="utf-8")
    assert main(["repo", "check-title", "msg"]) == 0
    assert capsys.readouterr().out.strip() == "title: ok"


def test_check_title_refuses_with_exit_1_and_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(title_checkout(tmp_path))
    (tmp_path / "msg").write_text("web: Added the guide.\n", encoding="utf-8")
    assert main(["repo", "check-title", "msg"]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert out[0].startswith("title refused: 'web: Added the guide.'") and "unknown area 'web'" in out[0]
    assert "AGENTS.md" in out[0]


def test_check_title_reads_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(title_checkout(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("docs: Add the guide\n"))
    assert main(["repo", "check-title", "-"]) == 0


def test_check_title_with_unusable_rules_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(title_checkout(tmp_path))
    (tmp_path / ".github" / "commit-conventions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "msg").write_text("docs: Add the guide\n", encoding="utf-8")
    assert main(["repo", "check-title", "msg"]) == 2
    err = capsys.readouterr().err
    assert "commit-conventions.json" in err and "Traceback" not in err


def test_check_title_with_an_unreadable_file_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(title_checkout(tmp_path))
    assert main(["repo", "check-title", "missing.txt"]) == 2
    assert "missing.txt" in capsys.readouterr().err


def test_check_title_of_an_empty_message_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(title_checkout(tmp_path))
    (tmp_path / "msg").write_text("\n# only a comment\n", encoding="utf-8")
    assert main(["repo", "check-title", "msg"]) == 1


def test_check_docs_passes_when_the_docs_change_with_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("src/core/a.cpp\nresearch/references/cars.yaml\n"))
    assert main(["repo", "check-docs"]) == 0


def test_check_docs_passes_for_changes_that_are_not_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(".github/workflows/pr.yml\npython/tests/test_cli.py\ntests/a.cpp\n"))
    assert main(["repo", "check-docs"]) == 0


def test_check_docs_refuses_code_without_docs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("python/src/coney_tools/wad.py\nsrc/core/a.cpp\n"))
    assert main(["repo", "check-docs"]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith(
        "docs refused: changes code (python/src/coney_tools/wad.py, src/core/a.cpp)"
    )
    assert "Docs: none" in out[0]


def test_check_docs_accepts_a_docs_none_line_in_the_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "body.md").write_text(
        "## What and why\n\nA rename.\n\ndocs: NONE - no behaviour change\n", encoding="utf-8"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("src\\core\\a.cpp\n"))
    assert main(["repo", "check-docs", "--body", str(tmp_path / "body.md")]) == 0


def test_check_docs_ignores_a_docs_none_inside_a_sentence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "body.md").write_text("I will say Docs: none later.\n", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("src/core/a.cpp\n"))
    assert main(["repo", "check-docs", "--body", str(tmp_path / "body.md")]) == 1


def test_check_docs_with_an_unreadable_body_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("src/core/a.cpp\n"))
    assert main(["repo", "check-docs", "--body", str(tmp_path / "missing.md")]) == 2
    assert "cannot be read" in capsys.readouterr().err
