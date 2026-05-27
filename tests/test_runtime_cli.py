import socket
import sys
import types

from whywiki.config import get_data_dir
from whywiki.runtime import (
    PortInUseError,
    ProcessInfo,
    RuntimePaths,
    append_runtime_log,
    choose_port,
    clear_runtime_state,
    default_runtime_paths,
    find_listening_process,
    read_active_runtime_state,
    read_log_tail,
    read_runtime_state,
    write_runtime_state,
)
from whywiki.cli import main


def test_runtime_state_round_trip(tmp_path):
    paths = RuntimePaths(tmp_path)
    write_runtime_state(paths, host="127.0.0.1", port=8765, pid=1234)

    state = read_runtime_state(paths)

    assert state["host"] == "127.0.0.1"
    assert state["port"] == 8765
    assert state["pid"] == 1234
    assert "started_at" in state


def test_clear_runtime_state_removes_state_file(tmp_path):
    paths = RuntimePaths(tmp_path)
    write_runtime_state(paths, host="127.0.0.1", port=8765, pid=1234)

    clear_runtime_state(paths)

    assert read_runtime_state(paths) is None


def test_append_runtime_log_creates_log_file(tmp_path):
    paths = RuntimePaths(tmp_path)

    append_runtime_log(paths, "WhyWiki started")

    assert "WhyWiki started\n" in paths.log_path.read_text(encoding="utf-8")


def test_default_runtime_paths_match_configured_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))

    assert default_runtime_paths().data_dir == get_data_dir()


def test_default_runtime_paths_match_config_default_in_current_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("WHYWIKI_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert default_runtime_paths().data_dir == get_data_dir()


def test_read_runtime_state_returns_none_for_corrupt_json(tmp_path):
    paths = RuntimePaths(tmp_path)
    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_text("{not json", encoding="utf-8")

    assert read_runtime_state(paths) is None


def test_read_runtime_state_returns_none_for_invalid_utf8(tmp_path):
    paths = RuntimePaths(tmp_path)
    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_bytes(b"\xff\xfe\xfa")

    assert read_runtime_state(paths) is None


def test_log_tail_returns_recent_lines(tmp_path):
    paths = RuntimePaths(tmp_path)
    paths.log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert read_log_tail(paths, lines=2) == "two\nthree\n"


def test_choose_port_returns_requested_free_port():
    port = choose_port("127.0.0.1", preferred=0)

    assert isinstance(port, int)
    assert port > 0


def test_choose_port_enables_address_reuse_for_fast_restart(monkeypatch):
    calls = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def setsockopt(self, level, option, value):
            calls.append((level, option, value))

        def bind(self, address):
            calls.append(("bind", address))

        def getsockname(self):
            return ("127.0.0.1", 8765)

    monkeypatch.setattr("whywiki.runtime.socket.socket", lambda *args, **kwargs: FakeSocket())

    assert choose_port("127.0.0.1", preferred=8765) == 8765
    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in calls


def test_choose_port_refuses_occupied_preferred_port():
    host = "127.0.0.1"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        occupied_port = int(sock.getsockname()[1])

        try:
            choose_port(host, preferred=occupied_port)
        except PortInUseError as exc:
            assert exc.host == host
            assert exc.port == occupied_port
        else:
            raise AssertionError("occupied preferred port should not fall back")


def test_find_listening_process_reads_pid_and_command(monkeypatch):
    def fake_run(*args, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout="p4321\ncpython3\n")

    monkeypatch.setattr("whywiki.runtime.subprocess.run", fake_run)

    assert find_listening_process("127.0.0.1", 8765) == ProcessInfo(4321, "python3")


def test_find_listening_process_falls_back_to_proc_socket_inodes(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        return types.SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr("whywiki.runtime.subprocess.run", fake_run)
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "tcp").write_text(
        "\n".join([
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode",
            "   0: 0100007F:223D 00000000:0000 0A 00000000:00000000 00:00000000 00000000 1000 0 98765 1",
        ]),
        encoding="utf-8",
    )
    process_dir = tmp_path / "4321"
    fd_dir = process_dir / "fd"
    fd_dir.mkdir(parents=True)
    (process_dir / "comm").write_text("python3\n", encoding="utf-8")
    (fd_dir / "3").symlink_to("socket:[98765]")

    assert find_listening_process("127.0.0.1", 8765, proc_root=tmp_path) == ProcessInfo(4321, "python3")


def test_active_runtime_state_returns_none_and_clears_stale_state(tmp_path):
    paths = RuntimePaths(tmp_path)
    write_runtime_state(paths, host="127.0.0.1", port=8765, pid=1234)

    state = read_active_runtime_state(paths, probe=lambda candidate: False)

    assert state is None
    assert read_runtime_state(paths) is None


def test_status_reports_not_running_without_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))

    assert main(["status"]) == 0

    assert '"running": false' in capsys.readouterr().out


def test_log_command_prints_recent_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    paths = RuntimePaths(tmp_path)
    paths.log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert main(["log", "--lines", "2"]) == 0

    assert capsys.readouterr().out == "two\nthree\n"


def test_serve_writes_actual_runtime_state_and_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("whywiki.cli.choose_port", lambda host, preferred: preferred)
    calls = []

    def record_run(app, host, port, reload):
        state = read_runtime_state(RuntimePaths(tmp_path))
        assert state is not None
        assert state["host"] == "127.0.0.1"
        assert state["port"] == 8765
        calls.append({"app": app, "host": host, "port": port, "reload": reload})

    fake_uvicorn = types.SimpleNamespace(
        run=record_run
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 0

    assert calls == [
        {
            "app": "whywiki.app:app",
            "host": "127.0.0.1",
            "port": 8765,
            "reload": False,
        }
    ]
    assert read_runtime_state(RuntimePaths(tmp_path)) is None
    output = capsys.readouterr().out
    assert "Open: http://127.0.0.1:8765" in output
    assert "Logs: whywiki log" in output
    log = RuntimePaths(tmp_path).log_path.read_text(encoding="utf-8")
    assert "Starting WhyWiki on http://127.0.0.1:8765" in log
    assert "WhyWiki server stopped." in log


def test_serve_reuses_active_runtime_state_without_starting_second_server(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    write_runtime_state(RuntimePaths(tmp_path), host="127.0.0.1", port=8765, pid=1234)
    monkeypatch.setattr("whywiki.cli.read_active_runtime_state", lambda paths: {
        "host": "127.0.0.1",
        "port": 8765,
        "pid": 1234,
    })

    def unexpected_run(*args, **kwargs):
        raise AssertionError("serve should not start a second server")

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=unexpected_run))

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 0

    output = capsys.readouterr().out
    assert "WhyWiki is already running on 127.0.0.1:8765." in output
    assert "Open: http://127.0.0.1:8765" in output
    assert "Logs: whywiki log" in output


def test_serve_prompts_for_existing_whywiki_and_continues_with_current_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    write_runtime_state(RuntimePaths(tmp_path), host="127.0.0.1", port=8765, pid=1234)
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    monkeypatch.setattr("whywiki.cli.read_active_runtime_state", lambda paths: {
        "host": "127.0.0.1",
        "port": 8765,
        "pid": 1234,
        "started_at": "2026-05-10T13:09:45+00:00",
    })

    def unexpected_run(*args, **kwargs):
        raise AssertionError("serve should not start a second server")

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=unexpected_run))

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 0

    output = capsys.readouterr().out
    assert "WhyWiki is already running on 127.0.0.1:8765." in output
    assert "PID: 1234" in output
    assert "Started: 2026-05-10T13:09:45+00:00" in output
    assert "1. Continue using the existing WhyWiki service." in output
    assert "2. Restart the WhyWiki service." in output
    assert "Open: http://127.0.0.1:8765" in output


def test_serve_prompts_for_existing_whywiki_and_restarts_service(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    write_runtime_state(RuntimePaths(tmp_path), host="127.0.0.1", port=8765, pid=1234)
    monkeypatch.setattr("builtins.input", lambda prompt: "2")
    monkeypatch.setattr("whywiki.cli.read_active_runtime_state", lambda paths: {
        "host": "127.0.0.1",
        "port": 8765,
        "pid": 1234,
        "started_at": "2026-05-10T13:09:45+00:00",
    })
    monkeypatch.setattr("whywiki.cli.stop_process", lambda pid: stopped.append(pid))
    monkeypatch.setattr("whywiki.cli.choose_port", lambda host, preferred: preferred)
    stopped = []
    calls = []

    def record_run(app, host, port, reload):
        calls.append({"app": app, "host": host, "port": port, "reload": reload})

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=record_run))

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 0

    assert stopped == [1234]
    assert calls == [{"app": "whywiki.app:app", "host": "127.0.0.1", "port": 8765, "reload": False}]
    output = capsys.readouterr().out
    assert "Restarting WhyWiki service on http://127.0.0.1:8765" in output


def test_serve_prompts_for_foreign_port_owner_and_cancels(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("whywiki.cli.read_active_runtime_state", lambda paths: None)
    monkeypatch.setattr("whywiki.cli.probe_whywiki_server", lambda state: False)
    monkeypatch.setattr(
        "whywiki.cli.choose_port",
        lambda host, preferred: (_ for _ in ()).throw(PortInUseError(host, preferred)),
    )
    monkeypatch.setattr("whywiki.cli.find_listening_process", lambda host, port: ProcessInfo(4321, "python"))
    monkeypatch.setattr("builtins.input", lambda prompt: "2")

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 2

    captured = capsys.readouterr()
    assert "Port 127.0.0.1:8765 is being used by another process." in captured.out
    assert "PID: 4321" in captured.out
    assert "Command: python" in captured.out
    assert "1. Kill the process using this port and start WhyWiki." in captured.out
    assert "2. Cancel startup." in captured.out
    assert "Open:" not in captured.out


def test_serve_prompts_for_foreign_port_owner_and_kills_before_starting(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("whywiki.cli.read_active_runtime_state", lambda paths: None)
    monkeypatch.setattr("whywiki.cli.probe_whywiki_server", lambda state: False)
    monkeypatch.setattr("whywiki.cli.find_listening_process", lambda host, port: ProcessInfo(4321, "python"))
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    stopped = []
    attempts = {"count": 0}

    def choose_after_kill(host, preferred):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PortInUseError(host, preferred)
        return preferred

    monkeypatch.setattr("whywiki.cli.choose_port", choose_after_kill)
    monkeypatch.setattr("whywiki.cli.stop_process", lambda pid: stopped.append(pid))
    calls = []

    def record_run(app, host, port, reload):
        calls.append({"app": app, "host": host, "port": port, "reload": reload})

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=record_run))

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 0

    assert stopped == [4321]
    assert calls == [{"app": "whywiki.app:app", "host": "127.0.0.1", "port": 8765, "reload": False}]
    output = capsys.readouterr().out
    assert "Starting WhyWiki after freeing 127.0.0.1:8765." in output


def test_serve_reports_unidentified_foreign_port_without_kill_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("whywiki.cli.read_active_runtime_state", lambda paths: None)
    monkeypatch.setattr("whywiki.cli.probe_whywiki_server", lambda state: False)
    monkeypatch.setattr("whywiki.cli.find_listening_process", lambda host, port: None)
    monkeypatch.setattr(
        "whywiki.cli.choose_port",
        lambda host, preferred: (_ for _ in ()).throw(PortInUseError(host, preferred)),
    )

    def unexpected_input(prompt):
        raise AssertionError("unidentified port owner should not offer a kill prompt")

    monkeypatch.setattr("builtins.input", unexpected_input)

    assert main(["serve", "--host", "127.0.0.1", "--port", "8765"]) == 2

    captured = capsys.readouterr()
    assert "Port 127.0.0.1:8765 is being used by another process." in captured.out
    assert "PID: unknown" in captured.out
    assert "1. Kill the process using this port and start WhyWiki." not in captured.out
    assert "WhyWiki could not identify the process using 127.0.0.1:8765" in captured.err
    assert "whywiki serve --host 127.0.0.1 --port <free-port>" in captured.err


def test_serve_clears_runtime_state_when_uvicorn_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("whywiki.cli.choose_port", lambda host, preferred: preferred)

    def raise_from_run(app, host, port, reload):
        assert port == 8765
        raise RuntimeError("server failed")

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=raise_from_run))

    try:
        main(["serve", "--host", "127.0.0.1", "--port", "8765"])
    except RuntimeError as exc:
        assert str(exc) == "server failed"
    else:
        raise AssertionError("uvicorn failure was not propagated")

    assert read_runtime_state(RuntimePaths(tmp_path)) is None
    assert "WhyWiki server stopped." in RuntimePaths(tmp_path).log_path.read_text(encoding="utf-8")


def test_doctor_reports_runtime_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))

    assert main(["doctor"]) == 0

    output = capsys.readouterr().out
    assert str(tmp_path.resolve()) in output
    assert '"state_file_exists": false' in output
    assert '"log_file_exists": false' in output


def test_open_prints_runtime_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WHYWIKI_DATA_DIR", str(tmp_path))
    write_runtime_state(RuntimePaths(tmp_path), host="127.0.0.1", port=8765, pid=1234)

    assert main(["open"]) == 0

    assert capsys.readouterr().out == "http://127.0.0.1:8765\n"


def test_stop_reports_not_active(capsys):
    assert main(["stop"]) == 0

    assert capsys.readouterr().out == "Stop is not active yet. Use Ctrl+C for foreground serve sessions.\n"
