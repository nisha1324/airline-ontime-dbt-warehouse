"""One throwaway warehouse build shared by every test that needs it."""
import os
import subprocess

import pytest

from scripts.build import dbt_executable
from scripts.download_data import ROOT


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory):
    db = tmp_path_factory.mktemp("wh") / "warehouse.duckdb"
    env = {**os.environ, "OTP_DUCKDB_PATH": str(db)}
    result = subprocess.run(
        [dbt_executable(), "build", "--no-use-colors",
         "--target-path", str(db.parent / "target"),
         "--log-path", str(db.parent / "logs")],
        cwd=ROOT / "warehouse", env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout[-3000:]
    return db, result.stdout
