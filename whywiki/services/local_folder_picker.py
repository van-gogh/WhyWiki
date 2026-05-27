from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .ingest import wsl_path_hint


class LocalFolderPickerUnavailable(RuntimeError):
    pass


def server_readable_folder_path(path_str: str) -> Path:
    hint = wsl_path_hint(path_str) if os.name != "nt" else None
    return Path(hint or path_str).expanduser().resolve()


def is_wsl() -> bool:
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def choose_windows_folder_from_wsl() -> Path | None:
    powershell = shutil.which("powershell.exe")
    if not powershell:
        raise LocalFolderPickerUnavailable(
            "WhyWiki is running in WSL, but powershell.exe is unavailable. "
            "Enter an absolute folder path that the WhyWiki server can read."
        )

    script = """
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Choose a folder for WhyWiki to scan'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  Write-Output $dialog.SelectedPath
}
""".strip()
    result = subprocess.run(
        [powershell, "-NoProfile", "-STA", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "The Windows folder picker failed to open."
        raise LocalFolderPickerUnavailable(
            f"WhyWiki could not open the Windows folder picker from WSL: {detail} "
            "Enter an absolute folder path that the WhyWiki server can read."
        )

    selected = result.stdout.strip()
    if not selected:
        return None
    return server_readable_folder_path(selected)


def choose_local_folder() -> Path | None:
    if is_wsl():
        return choose_windows_folder_from_wsl()

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise LocalFolderPickerUnavailable(
            "The local folder picker is unavailable because Python tkinter is not installed. "
            "Enter an absolute folder path that the WhyWiki server can read."
        ) from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        selected = filedialog.askdirectory(
            title="Choose a folder for WhyWiki to scan",
            mustexist=True,
            parent=root,
        )
    except tk.TclError as exc:
        raise LocalFolderPickerUnavailable(
            "WhyWiki could not open the local folder picker in this environment. "
            "Enter an absolute folder path that the WhyWiki server can read."
        ) from exc
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

    if not selected:
        return None
    return server_readable_folder_path(selected)
