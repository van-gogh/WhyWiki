from pathlib import Path
import os

from whywiki.db import connect, init_db
from whywiki.services.workspace import create_project
from whywiki.services.ingest import ingest_path
from whywiki.services.wiki_engine import build_project
from whywiki.services.ask import ask_project


def test_basic_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    init_db()
    project = create_project("Fixture Project")
    root = Path(__file__).resolve().parent / "fixtures" / "messy-project"
    result = ingest_path(project["id"], root)
    assert result["created_blocks"] > 0
    build = build_project(project["id"])
    assert build["facts_created"] > 0
    answer = ask_project(project["id"], "接口是什么？")
    assert "证据" in answer["answer"]


def test_ingest_missing_local_path_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    init_db()
    project = create_project("Missing Path Project")

    missing_path = tmp_path / "missing"
    try:
        ingest_path(project["id"], missing_path)
    except ValueError as exc:
        assert str(missing_path) in str(exc)
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("ingest_path should reject a missing local source path")


def test_ingest_windows_local_path_on_posix_explains_server_path_format(tmp_path, monkeypatch):
    if os.name == "nt":
        return

    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    init_db()
    project = create_project("Windows Path Project")
    windows_path = r"D:\Documents\work\Data\海缆投标"

    try:
        ingest_path(project["id"], windows_path)
    except ValueError as exc:
        message = str(exc)
        assert windows_path in message
        assert "Windows-style path" in message
        assert "/mnt/d/Documents/work/Data/海缆投标" in message
        assert "server is running on POSIX" in message
    else:
        raise AssertionError("ingest_path should explain Windows paths on POSIX servers")


def test_ingest_local_folder_without_supported_files_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path / "data"))
    init_db()
    project = create_project("Unsupported Files Project")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "image.png").write_bytes(b"not parsed")

    try:
        ingest_path(project["id"], source_root)
    except ValueError as exc:
        assert str(source_root) in str(exc)
        assert "No supported files found" in str(exc)
    else:
        raise AssertionError("ingest_path should reject folders with no supported files")
