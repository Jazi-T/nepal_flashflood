#!/usr/bin/env python3
"""Small health check confirming that Python works in this project."""

from datetime import datetime
from pathlib import Path
import platform
import sys


def main() -> None:
    project_dir = Path(__file__).resolve().parent

    print("Python is working!")
    print(f"Python version: {platform.python_version()}")
    print(f"Executable: {sys.executable}")
    print(f"Project folder: {project_dir}")
    print(f"Current time: {datetime.now().astimezone().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
