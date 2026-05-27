from __future__ import annotations

from types import SimpleNamespace

from whywiki.services import local_folder_picker


def test_choose_local_folder_uses_windows_picker_on_wsl(monkeypatch):
    monkeypatch.setattr(local_folder_picker, "is_wsl", lambda: True)
    monkeypatch.setattr(local_folder_picker.shutil, "which", lambda name: "/usr/bin/powershell.exe")
    monkeypatch.setattr(
        local_folder_picker.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="D:\\Documents\\work\\Data\\海缆投标\r\n",
            stderr="",
        ),
    )

    selected = local_folder_picker.choose_local_folder()

    assert str(selected) == "/mnt/d/Documents/work/Data/海缆投标"


def test_choose_local_folder_returns_none_when_windows_picker_is_cancelled(monkeypatch):
    monkeypatch.setattr(local_folder_picker, "is_wsl", lambda: True)
    monkeypatch.setattr(local_folder_picker.shutil, "which", lambda name: "/usr/bin/powershell.exe")
    monkeypatch.setattr(
        local_folder_picker.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="\r\n", stderr=""),
    )

    assert local_folder_picker.choose_local_folder() is None
