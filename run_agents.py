from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

BASE = "http://127.0.0.1:8000"
PAGES = {
    "patient": "/assistant",
    "clinical": "/demo",
}
LABELS = {
    "patient": "Agent 1 - Patient guidance",
    "clinical": "Agent 3 - Clinical record analysis",
}
ALIASES = {
    "agent1": "patient",
    "1": "patient",
    "patient": "patient",
    "agent3": "clinical",
    "3": "clinical",
    "clinical": "clinical",
    "record": "clinical",
}


def responds(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def port_open() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def ensure_server() -> None:
    if responds(BASE + PAGES["patient"]) and responds(BASE + PAGES["clinical"]):
        print("Server is already running.")
        return
    if port_open():
        print("Port 8000 is used by an older server. Stop it and run this launcher again.")
        raise SystemExit(1)

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    for _ in range(30):
        time.sleep(0.5)
        if responds(BASE + PAGES["patient"]) and responds(BASE + PAGES["clinical"]):
            print("Server started.")
            return
    print("Server did not start. Run: .venv\\Scripts\\python -m uvicorn backend.main:app --reload")
    raise SystemExit(1)


def open_agent(value: str) -> None:
    key = ALIASES.get(value.strip().lower())
    if key is None:
        print("Unknown agent. Use: agent1 or agent3")
        return
    ensure_server()
    url = f"{BASE}{PAGES[key]}?open=1"
    print(f"Opening {LABELS[key]} -> {url}")
    webbrowser.open(url)


def main() -> None:
    if len(sys.argv) > 1:
        for value in sys.argv[1:]:
            open_agent(value)
        return

    print("CoreCare launcher. Type agent1, agent3, or quit.")
    while True:
        try:
            value = input("corecare> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if value.lower() in {"quit", "exit", "q"}:
            break
        if value:
            open_agent(value)


if __name__ == "__main__":
    main()
