"""Developer helper commands.

Usage:
    python -m scripts.dev install
    python -m scripts.dev run
    python -m scripts.dev test
    python -m scripts.dev lint
    python -m scripts.dev format
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_command(command: list[str]) -> int:
    process = subprocess.run(command, cwd=ROOT)
    return process.returncode


def cmd_install(_: argparse.Namespace) -> int:
    return run_command(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
    )


def cmd_run(_: argparse.Namespace) -> int:
    return run_command([sys.executable, "app.py"])


def cmd_test(_: argparse.Namespace) -> int:
    return run_command([sys.executable, "-m", "pytest", "-q"])


def cmd_lint(_: argparse.Namespace) -> int:
    return run_command([sys.executable, "-m", "ruff", "check", "."])


def cmd_format(_: argparse.Namespace) -> int:
    return run_command([sys.executable, "-m", "black", "."])


COMMANDS = {
    "install": cmd_install,
    "run": cmd_run,
    "test": cmd_test,
    "lint": cmd_lint,
    "format": cmd_format,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Developer helper commands")
    parser.add_argument("command", choices=COMMANDS.keys())
    args = parser.parse_args()
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
