from __future__ import annotations

from datetime import datetime, timezone
from errno import EADDRINUSE
import ipaddress
import json
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .config import get_data_dir


class PortInUseError(OSError):
    def __init__(self, host: str, port: int):
        super().__init__(EADDRINUSE, f"Port {host}:{port} is already in use")
        self.host = host
        self.port = port


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str = "unknown"


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "run"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def state_path(self) -> Path:
        return self.run_dir / "server.json"

    @property
    def log_path(self) -> Path:
        return self.log_dir / "whywiki.log"


def default_runtime_paths() -> RuntimePaths:
    return RuntimePaths(get_data_dir())


LISTEN_STATE = "0A"


def ensure_runtime_dirs(paths: RuntimePaths) -> None:
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)


def choose_port(host: str = "127.0.0.1", preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, preferred))
        except OSError as exc:
            if exc.errno != EADDRINUSE:
                raise
            raise PortInUseError(host, preferred) from exc
        return int(sock.getsockname()[1])


def write_runtime_state(paths: RuntimePaths, host: str, port: int, pid: int) -> None:
    ensure_runtime_dirs(paths)
    payload = {
        "host": host,
        "port": port,
        "pid": pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    paths.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_runtime_state(paths: RuntimePaths) -> None:
    try:
        paths.state_path.unlink()
    except FileNotFoundError:
        return


def append_runtime_log(paths: RuntimePaths, line: str) -> None:
    ensure_runtime_dirs(paths)
    with paths.log_path.open("a", encoding="utf-8") as log:
        log.write(line.rstrip("\n") + "\n")


def read_runtime_state(paths: RuntimePaths) -> dict[str, Any] | None:
    try:
        return json.loads(paths.state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def probe_whywiki_server(state: dict[str, Any], timeout: float = 0.5) -> bool:
    try:
        host = str(state["host"])
        port = int(state["port"])
    except (KeyError, TypeError, ValueError):
        return False

    try:
        with urlopen(f"http://{host}:{port}/", timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
    except (HTTPError, OSError, URLError, TimeoutError, ValueError):
        return False
    return "WhyWiki" in body


def process_command(pid: int, proc_root: Path = Path("/proc")) -> str:
    comm_path = proc_root / str(pid) / "comm"
    try:
        command = comm_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        command = ""
    if command:
        return command

    cmdline_path = proc_root / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return "unknown"
    parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    if not parts:
        return "unknown"
    return Path(parts[0]).name or parts[0]


def proc_tcp_address(hex_address: str) -> str | None:
    try:
        raw = bytes.fromhex(hex_address)
    except ValueError:
        return None
    if len(raw) == 4:
        return str(ipaddress.IPv4Address(bytes(reversed(raw))))
    return None


def listener_matches_host(listener_host: str, requested_host: str) -> bool:
    if listener_host == requested_host:
        return True
    if listener_host == "0.0.0.0":
        return True
    if requested_host == "0.0.0.0":
        return True
    return False


def listening_socket_inodes(host: str, port: int, proc_root: Path = Path("/proc")) -> set[str]:
    inodes: set[str] = set()
    tcp_path = proc_root / "net" / "tcp"
    try:
        lines = tcp_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return inodes

    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != LISTEN_STATE:
            continue
        local_address, _, local_port = fields[1].partition(":")
        try:
            parsed_port = int(local_port, 16)
        except ValueError:
            continue
        if parsed_port != port:
            continue
        listener_host = proc_tcp_address(local_address)
        if listener_host is None or not listener_matches_host(listener_host, host):
            continue
        inodes.add(fields[9])
    return inodes


def find_process_by_socket_inodes(inodes: set[str], proc_root: Path = Path("/proc")) -> ProcessInfo | None:
    if not inodes:
        return None

    try:
        process_dirs = sorted(proc_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return None

    for process_dir in process_dirs:
        if not process_dir.name.isdigit():
            continue
        try:
            pid = int(process_dir.name)
        except ValueError:
            continue
        fd_dir = process_dir / "fd"
        try:
            fd_paths = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd_path in fd_paths:
            try:
                target = os.readlink(fd_path)
            except OSError:
                continue
            if target.startswith("socket:[") and target.removeprefix("socket:[").removesuffix("]") in inodes:
                return ProcessInfo(pid=pid, command=process_command(pid, proc_root))
    return None


def find_listening_process(host: str, port: int, proc_root: Path = Path("/proc")) -> ProcessInfo | None:
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-F", "pc"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        result = None

    pid: int | None = None
    command = ""
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith("p"):
                try:
                    pid = int(line[1:])
                except ValueError:
                    pid = None
            elif line.startswith("c") and line[1:]:
                command = line[1:]
            if pid is not None and command:
                return ProcessInfo(pid=pid, command=command)
        if pid is not None:
            return ProcessInfo(pid=pid)
    return find_process_by_socket_inodes(listening_socket_inodes(host, port, proc_root), proc_root)


def stop_process(pid: int, timeout: float = 5.0) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    os.kill(pid, signal.SIGKILL)


def read_active_runtime_state(
    paths: RuntimePaths,
    probe: Callable[[dict[str, Any]], bool] = probe_whywiki_server,
) -> dict[str, Any] | None:
    state = read_runtime_state(paths)
    if state is None:
        return None
    if probe(state):
        return state
    clear_runtime_state(paths)
    return None


def read_log_tail(paths: RuntimePaths, lines: int = 80) -> str:
    if not paths.log_path.exists():
        return "No WhyWiki log file found.\n"
    content = paths.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:]) + ("\n" if content else "")
