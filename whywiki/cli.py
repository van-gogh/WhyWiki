from __future__ import annotations

import argparse
import json
import os
import sys

from .collaboration.accounts import AccountStore
from .collaboration.artifacts import (
    WorkspaceArtifactPaths,
    load_workspace_config,
    save_workspace_config,
)
from .collaboration.env import static_provider_registry_from_env
from .collaboration.models import ProviderIdentity, RepoRef, WorkspaceConfig
from .config import get_data_dir
from .db import init_db
from .runtime import (
    PortInUseError,
    ProcessInfo,
    append_runtime_log,
    choose_port,
    clear_runtime_state,
    default_runtime_paths,
    find_listening_process,
    probe_whywiki_server,
    read_active_runtime_state,
    read_log_tail,
    stop_process,
    write_runtime_state,
)
from .services.ask import ask_project
from .services.collaboration import CollaborationService
from .services.ingest import ingest_path
from .services.wiki_engine import build_project
from .services.workspace import create_project, list_projects


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def account_store() -> AccountStore:
    return AccountStore(get_data_dir() / "auth" / "accounts.json")


def workspace_paths() -> WorkspaceArtifactPaths:
    return WorkspaceArtifactPaths(get_data_dir() / "workspace")


def prompt_choice(prompt: str, choices: set[str], default: str) -> str:
    try:
        answer = input(prompt).strip()
    except (EOFError, OSError):
        return default
    if answer in choices:
        return answer
    print(f"Invalid choice: {answer or '<empty>'}. Using {default}.")
    return default


def print_running_whywiki_options(state: dict[str, object]) -> str:
    host = state.get("host", "127.0.0.1")
    port = state.get("port", 8765)
    print(f"WhyWiki is already running on {host}:{port}.")
    if state.get("pid") is not None:
        print(f"PID: {state['pid']}")
    if state.get("started_at") is not None:
        print(f"Started: {state['started_at']}")
    print("1. Continue using the existing WhyWiki service.")
    print("2. Restart the WhyWiki service.")
    return prompt_choice("Choose 1 or 2: ", {"1", "2"}, default="1")


def print_foreign_port_options(host: str, port: int, owner: ProcessInfo) -> str:
    print(f"Port {host}:{port} is being used by another process.")
    print(f"PID: {owner.pid}")
    print(f"Command: {owner.command}")
    print("1. Kill the process using this port and start WhyWiki.")
    print("2. Cancel startup.")
    return prompt_choice("Choose 1 or 2: ", {"1", "2"}, default="2")


def print_unidentified_port_error(host: str, port: int) -> None:
    print(f"Port {host}:{port} is being used by another process.")
    print("PID: unknown")
    print("Command: unknown")
    print(
        f"WhyWiki could not identify the process using {host}:{port}, so it cannot safely stop it.",
        file=sys.stderr,
    )
    print("Stop that process manually, or start WhyWiki on another port with:", file=sys.stderr)
    print(f"  whywiki serve --host {host} --port <free-port>", file=sys.stderr)


def state_pid(state: dict[str, object], host: str, port: int) -> int | None:
    try:
        return int(state["pid"])
    except (KeyError, TypeError, ValueError):
        owner = find_listening_process(host, port)
        return owner.pid if owner else None


def run_server(host: str, port: int, paths, restart: bool = False) -> int:
    import uvicorn

    url = f"http://{host}:{port}"
    write_runtime_state(paths, host=host, port=port, pid=os.getpid())
    append_runtime_log(paths, f"Starting WhyWiki on {url}")
    if restart:
        print(f"Restarting WhyWiki service on {url}")
    else:
        print("WhyWiki is running locally.")
    print(f"Open: {url}")
    try:
        uvicorn.run("whywiki.app:app", host=host, port=port, reload=False)
        return 0
    finally:
        append_runtime_log(paths, "WhyWiki server stopped.")
        clear_runtime_state(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="whywiki")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db")

    p_create = sub.add_parser("create")
    p_create.add_argument("name")
    p_create.add_argument("--description", default="")

    sub.add_parser("list")

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("project_id")
    p_ingest.add_argument("path")
    p_ingest.add_argument("--source-type", default="local", choices=["local", "git"])

    p_build = sub.add_parser("build")
    p_build.add_argument("project_id")

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("project_id")
    p_ask.add_argument("question")

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)

    sub.add_parser("open")
    sub.add_parser("status")

    p_log = sub.add_parser("log")
    p_log.add_argument("--lines", type=int, default=80)

    sub.add_parser("doctor")
    sub.add_parser("stop")

    p_auth = sub.add_parser("auth")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("list")

    p_auth_login = auth_sub.add_parser("login")
    p_auth_login.add_argument("provider", choices=["github", "gitea"])
    p_auth_login.add_argument("--account", required=True)
    p_auth_login.add_argument("--provider-user-id", required=True)
    p_auth_login.add_argument("--base-url")

    p_workspace = sub.add_parser("workspace")
    workspace_sub = p_workspace.add_subparsers(dest="workspace_command", required=True)

    p_workspace_connect = workspace_sub.add_parser("connect")
    p_workspace_connect.add_argument("provider", choices=["github", "gitea"])
    p_workspace_connect.add_argument("repo")
    p_workspace_connect.add_argument("--base-url")

    workspace_sub.add_parser("status")

    args = parser.parse_args(argv)

    if args.command == "init-db":
        init_db()
        print("WhyWiki database initialized.")
        return 0

    if args.command == "create":
        print(json.dumps(create_project(args.name, args.description), ensure_ascii=False, indent=2))
        return 0

    if args.command == "list":
        print(json.dumps(list_projects(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ingest":
        print(json.dumps(ingest_path(args.project_id, args.path, args.source_type), ensure_ascii=False, indent=2))
        return 0

    if args.command == "build":
        print(json.dumps(build_project(args.project_id), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ask":
        result = ask_project(args.project_id, args.question)
        print(result["answer"])
        return 0

    if args.command == "auth":
        if args.auth_command == "list":
            print_json({
                "connected_accounts": [
                    identity.to_dict()
                    for identity in account_store().list_identities()
                ]
            })
            return 0

        if args.auth_command == "login":
            try:
                identity = ProviderIdentity(
                    provider=args.provider,
                    account=args.account,
                    provider_user_id=args.provider_user_id,
                    base_url=args.base_url,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            account_store().save_identity(identity)
            print_json(identity.to_dict())
            return 0

    if args.command == "workspace":
        paths = workspace_paths()
        if args.workspace_command == "connect":
            try:
                config = WorkspaceConfig(
                    workspace=RepoRef(
                        provider=args.provider,
                        repo=args.repo,
                        base_url=args.base_url,
                    )
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            save_workspace_config(paths, config)
            print_json({"workspace": config.workspace.to_dict()})
            return 0

        if args.workspace_command == "status":
            if not paths.workspace_config_path.exists():
                print_json({"configured": False, "workspace": None, "projects": {}, "access": None})
                return 0
            config = load_workspace_config(paths)
            access = CollaborationService(config, static_provider_registry_from_env()).check_workspace(project_slug=None)
            print_json({"configured": True, **config.to_dict(), "access": access.to_dict()})
            return 0

    if args.command == "serve":
        paths = default_runtime_paths()
        active_state = read_active_runtime_state(paths)
        if active_state is not None:
            choice = print_running_whywiki_options(active_state)
            url = f"http://{active_state['host']}:{active_state['port']}"
            if choice == "1":
                print(f"Open: {url}")
                return 0

            pid = state_pid(active_state, str(active_state["host"]), int(active_state["port"]))
            if pid is None:
                print("Could not identify the running WhyWiki process. Canceling restart.", file=sys.stderr)
                return 2
            stop_process(pid)
            clear_runtime_state(paths)
            port = choose_port(args.host, preferred=args.port)
            return run_server(args.host, port, paths, restart=True)

        try:
            port = choose_port(args.host, preferred=args.port)
        except PortInUseError:
            port_state = {"host": args.host, "port": args.port}
            if probe_whywiki_server(port_state):
                owner = find_listening_process(args.host, args.port)
                whywiki_state = dict(port_state)
                if owner is not None:
                    whywiki_state["pid"] = owner.pid
                choice = print_running_whywiki_options(whywiki_state)
                if choice == "1":
                    print(f"Open: http://{args.host}:{args.port}")
                    return 0
                if owner is None:
                    print("Could not identify the running WhyWiki process. Canceling restart.", file=sys.stderr)
                    return 2
                stop_process(owner.pid)
                clear_runtime_state(paths)
                port = choose_port(args.host, preferred=args.port)
                return run_server(args.host, port, paths, restart=True)

            owner = find_listening_process(args.host, args.port)
            if owner is None:
                print_unidentified_port_error(args.host, args.port)
                append_runtime_log(paths, f"Startup canceled because {args.host}:{args.port} is occupied by an unidentified process.")
                return 2
            choice = print_foreign_port_options(args.host, args.port, owner)
            if choice == "2":
                append_runtime_log(paths, f"Startup canceled because {args.host}:{args.port} is occupied.")
                return 2
            stop_process(owner.pid)
            clear_runtime_state(paths)
            print(f"Starting WhyWiki after freeing {args.host}:{args.port}.")
            port = choose_port(args.host, preferred=args.port)

        return run_server(args.host, port, paths)

    if args.command == "status":
        state = read_active_runtime_state(default_runtime_paths())
        print(json.dumps(state or {"running": False}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "log":
        print(read_log_tail(default_runtime_paths(), args.lines), end="")
        return 0

    if args.command == "doctor":
        paths = default_runtime_paths()
        print(json.dumps({
            "data_dir": str(paths.data_dir),
            "state_file_exists": paths.state_path.exists(),
            "log_file_exists": paths.log_path.exists(),
        }, ensure_ascii=False, indent=2))
        return 0

    if args.command == "open":
        state = read_active_runtime_state(default_runtime_paths()) or {}
        url = f"http://{state.get('host', '127.0.0.1')}:{state.get('port', 8765)}"
        print(url)
        return 0

    if args.command == "stop":
        print("Stop is not active yet. Use Ctrl+C for foreground serve sessions.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
