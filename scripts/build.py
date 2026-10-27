"""Build the warehouse: verify the snapshot, then `dbt build` (seeds, models, tests).

    python scripts/build.py            # -> data/warehouse.duckdb
    python scripts/build.py --select staging

dbt runs from warehouse/ because the snapshot path in dbt_project.yml is
relative to that folder. Any extra arguments are passed through to dbt.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.download_data import verify  # noqa: E402


def dbt_executable() -> str:
    # Prefer the dbt next to the running interpreter (the project's venv).
    local = Path(sys.executable).with_name("dbt")
    if local.exists():
        return str(local)
    found = shutil.which("dbt")
    if not found:
        raise SystemExit("dbt not found: pip install -r requirements.txt")
    return found


def main(argv: list[str]) -> int:
    verify()
    cmd = [dbt_executable(), "build", "--no-use-colors", *argv]
    return subprocess.run(cmd, cwd=ROOT / "warehouse").returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
