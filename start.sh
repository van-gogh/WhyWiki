#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

cd "$ROOT_DIR"

find_python() {
  for candidate in python3.12 python3.11 python3.10 python3 python; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1
    then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

ensure_venv() {
  if [[ -x "$VENV_PYTHON" ]]; then
    return 0
  fi

  local python_bin
  if ! python_bin="$(find_python)"; then
    echo "WhyWiki needs Python 3.10 or newer. Install Python 3.10+ and run ./start.sh again." >&2
    exit 1
  fi

  echo "Creating .venv with python -m venv..."
  "$python_bin" -m venv "$VENV_DIR"
}

ensure_pip() {
  if "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    return 0
  fi

  echo "Installing pip into .venv with ensurepip..."
  "$VENV_PYTHON" -m ensurepip --upgrade
}

install_whywiki() {
  echo "Installing WhyWiki into .venv..."
  "$VENV_PYTHON" -m pip install -e .
}

restart_existing_whywiki() {
  "$VENV_PYTHON" - <<'PY'
from whywiki.runtime import (
    PortInUseError,
    clear_runtime_state,
    choose_port,
    default_runtime_paths,
    find_listening_process,
    read_active_runtime_state,
    stop_process,
)

host = "127.0.0.1"
port = 8765
paths = default_runtime_paths()
state = read_active_runtime_state(paths)
pid = None

if state is not None and str(state.get("host")) == host and int(state.get("port", 0)) == port:
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        pid = None

owner = find_listening_process(host, port)
if pid is None and owner is not None:
    pid = owner.pid

if pid is None:
    try:
        choose_port(host, port)
    except PortInUseError:
        print(f"Port {host}:{port} is already occupied, but WhyWiki could not identify the process using it.")
        print("Stop that process manually, or start WhyWiki on another port with:")
        print(f"  whywiki serve --host {host} --port <free-port>")
        raise SystemExit(2)
    print(f"No existing WhyWiki service found on {host}:{port}.")
else:
    print(f"Stopping existing WhyWiki service on {host}:{port} (pid {pid})...")
    stop_process(pid)

clear_runtime_state(paths)
PY
}

ensure_venv
ensure_pip
install_whywiki

export WHYWIKI_DATA_DIR="${WHYWIKI_DATA_DIR:-$ROOT_DIR/.whywiki}"

restart_existing_whywiki

echo "Initializing WhyWiki database..."
"$VENV_PYTHON" -m whywiki.cli init-db

echo
echo "WhyWiki local URL:"
echo "http://127.0.0.1:8765"
echo

exec "$VENV_PYTHON" -m whywiki.cli serve --host 127.0.0.1 --port 8765
