"""Build the dbt project into a throwaway DuckDB file and check what it produced."""
import os
import subprocess
import sys

import duckdb
import pytest

from scripts.build import dbt_executable
from scripts.download_data import ROOT

STG = "stg_bitre__otp_monthly"


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


def test_dbt_build_has_no_errors(warehouse):
    _, stdout = warehouse
    assert "ERROR=0" in stdout


def test_every_source_row_is_staged_once(warehouse):
    db, _ = warehouse
    con = duckdb.connect(str(db), read_only=True)
    n, distinct = con.sql(f"select count(*), count(distinct otp_row_id) from {STG}").fetchone()
    assert n == distinct == 119_970


def test_each_row_has_exactly_one_grain(warehouse):
    db, _ = warehouse
    con = duckdb.connect(str(db), read_only=True)
    grains = dict(con.sql(f"select row_grain, count(*) from {STG} group by 1").fetchall())
    assert grains == {
        "route_airline": 87_176,
        "route_all_airlines": 30_603,
        "network_airline": 1_918,
        "network_all_airlines": 273,
    }


def test_warehouse_file_is_self_contained(warehouse, tmp_path, monkeypatch):
    # Opened from another folder, the staged table must still read: no view
    # that points back at a relative CSV path.
    db, _ = warehouse
    monkeypatch.chdir(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    assert con.sql(f"select count(*) from {STG}").fetchone()[0] == 119_970


def test_committed_profile_matches_a_fresh_build(warehouse, tmp_path):
    db, _ = warehouse
    out = tmp_path / "SOURCE_PROFILE.md"
    subprocess.run([sys.executable, "scripts/profile_source.py", "--db", str(db),
                    "--out", str(out)], cwd=ROOT, check=True, capture_output=True)
    committed = (ROOT / "results" / "SOURCE_PROFILE.md").read_text()
    assert out.read_text() == committed, "results/SOURCE_PROFILE.md is stale: rerun profile_source.py"
