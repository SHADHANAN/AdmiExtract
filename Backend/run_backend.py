"""
AdmiExtract Backend Development Runner
======================================
Safe launcher and port conflict manager for Uvicorn backend.
- Prevents Errno 10048 (duplicate port binding)
- Identifies active backend PIDs and checks health
- Supports graceful restart with --restart
- Preserves 0.0.0.0:8000 for Cloudflare Quick Tunnel compatibility

Usage:
  python run_backend.py              # Start backend (or reuse existing)
  python run_backend.py --restart    # Safely restart existing backend
  python run_backend.py --status     # Check running backend status
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# Add backend root to sys.path so app modules are resolvable
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.core.config import settings
    DEFAULT_PUBLIC_URL = getattr(settings, "PUBLIC_APP_URL", "")
except Exception:
    DEFAULT_PUBLIC_URL = ""

CLOUDFLARE_DEFAULT = "https://winner-removal-adding-style.trycloudflare.com"


def find_pid_on_port(port: int) -> int | None:
    """Find the process ID listening on the given TCP port."""
    try:
        res = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
                # Check for :<port> binding at end of local address
                if parts[1].endswith(f":{port}"):
                    try:
                        return int(parts[4])
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass
    return None


def get_process_command_line(pid: int) -> str:
    """Retrieve command line for a given PID on Windows."""
    try:
        cmd = f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=3,
        )
        output = res.stdout.strip()
        if output:
            return output
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        line = res.stdout.strip()
        if line and not line.startswith("INFO:"):
            return line.split(",")[0].strip('"')
    except Exception:
        pass

    return f"Process (PID {pid})"


def is_admiextract_backend(pid: int) -> bool:
    """Verify if the PID belongs to an AdmiExtract uvicorn/python process."""
    cmdline = get_process_command_line(pid).lower()
    return any(marker in cmdline for marker in ("admiextract", "uvicorn", "app.main"))


def kill_process_safely(pid: int) -> bool:
    """Terminate a process tree by PID safely."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to terminate PID {pid}: {e}")
        return False


def wait_port_freed(port: int, timeout_sec: float = 5.0) -> bool:
    """Wait until the port is released."""
    start = time.time()
    while time.time() - start < timeout_sec:
        if find_pid_on_port(port) is None:
            return True
        time.sleep(0.3)
    return False


def verify_port_available(host: str = "0.0.0.0", port: int = 8000) -> str | None:
    """
    Check if a port is available or already occupied.
    Returns None if available, or a diagnostic error message if occupied.
    """
    occupant_pid = find_pid_on_port(port)
    if occupant_pid is not None and occupant_pid != os.getpid():
        cmdline = get_process_command_line(occupant_pid)
        return f"Port {port} on '{host}' is already in use by PID {occupant_pid} ({cmdline})."

    # Secondary socket probe
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE") and sys.platform == "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
    except OSError as e:
        return f"Port {port} on '{host}' cannot be bound: {e}"

    return None


def print_already_running_banner(pid: int, port: int, tunnel_url: str | None = None) -> None:
    """Print standard friendly already-running banner."""
    url = tunnel_url or CLOUDFLARE_DEFAULT
    print("=" * 55)
    print(" AdmiExtract Backend Already Running")
    print("=" * 55)
    print(f" PID: {pid}")
    print(f" URL: http://localhost:{port}")
    print(" Cloudflare Tunnel:")
    print(f" {url}\n")
    print(" Reusing the existing backend.")
    print(" No second Uvicorn instance will be started.")
    print("=" * 55)


def run(host: str = "0.0.0.0", port: int = 8000, reload: bool = True, restart: bool = False, status: bool = False) -> int:
    """Run backend launch management logic. Returns process exit code."""
    tunnel_url = DEFAULT_PUBLIC_URL if "trycloudflare.com" in DEFAULT_PUBLIC_URL else CLOUDFLARE_DEFAULT
    existing_pid = find_pid_on_port(port)

    # Status check mode
    if status:
        if existing_pid:
            cmd = get_process_command_line(existing_pid)
            print(f"[STATUS] Backend is ACTIVE on port {port} (PID: {existing_pid})")
            print(f"[STATUS] Command line: {cmd}")
            print(f"[STATUS] Local: http://localhost:{port}")
            print(f"[STATUS] Docs:  http://localhost:{port}/docs")
            print(f"[STATUS] Cloudflare Tunnel: {tunnel_url}")
        else:
            print(f"[STATUS] No process is currently listening on port {port}.")
        return 0

    # If port is in use
    if existing_pid:
        cmdline = get_process_command_line(existing_pid)
        is_our_backend = is_admiextract_backend(existing_pid)

        if restart:
            if not is_our_backend:
                print(f"[ERROR] Port {port} is occupied by an external application (PID {existing_pid}):")
                print(f"  {cmdline}")
                print("Refusing to terminate unrelated process. Please choose a different port or stop it manually.")
                return 1

            print(f"[INFO] Terminating existing AdmiExtract backend (PID {existing_pid})...")
            kill_process_safely(existing_pid)
            if wait_port_freed(port):
                print(f"[INFO] Port {port} freed successfully.")
            else:
                print(f"[ERROR] Port {port} could not be freed in time.")
                return 1
        else:
            # Normal start: port already in use
            if not is_our_backend:
                print(f"[ERROR] Port {port} is already occupied by an external application (PID {existing_pid}):")
                print(f"  {cmdline}")
                print("Refusing to start. Please choose a different port or terminate the conflicting process.")
                return 1

            # It is our backend - print standard banner and reuse
            print_already_running_banner(existing_pid, port, tunnel_url)
            return 0

    # Start Uvicorn
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload:
        cmd.append("--reload")

    print("[INFO] Launching canonical backend command:")
    print(f"       {' '.join(cmd)}\n")
    try:
        proc = subprocess.run(cmd, cwd=str(BACKEND_DIR))
        return proc.returncode
    except KeyboardInterrupt:
        print("\n[INFO] Backend stopped by user.")
        return 0


def main():
    parser = argparse.ArgumentParser(description="AdmiExtract Safe Backend Runner")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Binding port (default: 8000)")
    parser.add_argument("--reload", action="store_true", default=True, help="Enable auto-reload")
    parser.add_argument("--restart", action="store_true", help="Restart existing backend if running")
    parser.add_argument("--status", action="store_true", help="Check current backend status")
    args = parser.parse_args()

    exit_code = run(
        host=args.host,
        port=args.port,
        reload=args.reload,
        restart=args.restart,
        status=args.status,
    )
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
