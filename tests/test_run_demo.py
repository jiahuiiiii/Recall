"""Safety checks for the one-memo command-line entry point."""

from pathlib import Path

import run_demo


def test_reset_respects_isolated_storage_paths(tmp_path, monkeypatch):
    paths = {
        "RECALL_STORE_PATH": tmp_path / "people.json",
        "RECALL_CALENDAR_PATH": tmp_path / "calendar.json",
        "RECALL_RELATIONS_PATH": tmp_path / "relations.json",
    }
    for key, path in paths.items():
        path.write_text("{}")
        monkeypatch.setenv(key, str(path))

    missing_memo = tmp_path / "missing.txt"
    assert run_demo.main(["--reset", str(missing_memo)]) == 1
    assert all(not Path(path).exists() for path in paths.values())
