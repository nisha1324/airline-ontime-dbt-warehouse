"""Export the star schema to Parquet for Power BI: powerbi/data/*.parquet.

    python scripts/build.py && python scripts/export_powerbi.py

Power BI Desktop runs on Windows and has no DuckDB connector out of the box,
but it reads Parquet natively (Power Query's Parquet.Document). The files are
small and committed, so the model can be built from a clone with no Python.

After writing each file the script reads it back with a fresh DuckDB
connection and checks it against the warehouse: row count, column names and
types, null counts and the total of every numeric column. A mismatch stops the
export. MANIFEST.json records those figures (and powerbi/POWERBI_GUIDE.md
lists the Power BI type for each column).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.profile_source import DB, ROOT  # noqa: E402

OUT = ROOT / "powerbi" / "data"

# (table, sort key). Rows are written in key order so a rebuild of the same
# snapshot writes the same file.
TABLES = [
    ("fct_route_month", "route_month_id"),
    ("fct_network_month", "network_month_id"),
    ("dim_airline", "airline_key"),
    ("dim_route", "route_key"),
    ("dim_port", "port_key"),
    ("dim_month", "month_key"),
    ("dim_comparison_period", "sort_order"),
]

NUMERIC = ("DOUBLE", "INTEGER", "BIGINT")


def profile(con, relation: str) -> dict:
    """Row count, schema, null counts and numeric totals of a table or file."""
    columns = con.sql(f"describe select * from {relation}").fetchall()
    exprs = ["count(*)"]
    for name, dtype, *_ in columns:
        exprs.append(f'count(*) - count("{name}")')
        if dtype in NUMERIC:
            exprs.append(f'sum("{name}")')
    values = list(con.sql(f"select {', '.join(exprs)} from {relation}").fetchone())
    out = {"rows": values.pop(0), "columns": []}
    for name, dtype, *_ in columns:
        col = {"name": name, "type": dtype, "nulls": values.pop(0)}
        if dtype in NUMERIC:
            total = values.pop(0)
            # Rounded so float summation order can't change the manifest.
            col["sum"] = round(float(total), 4) if dtype == "DOUBLE" else int(total)
        out["columns"].append(col)
    return out


def export(db: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db), read_only=True)
    manifest = {"source": "data/warehouse.duckdb (dbt build)", "tables": {}}
    for table, key in TABLES:
        path = out / f"{table}.parquet"
        con.sql(f"copy (select * from {table} order by {key}) "
                f"to '{path}' (format parquet, compression zstd)")
        expected = profile(con, table)
        got = profile(duckdb.connect(), f"read_parquet('{path}')")
        if got != expected:
            raise SystemExit(f"{path.name} doesn't match {table}:\n{expected}\n{got}")
        manifest["tables"][table] = expected
        print(f"wrote {path.name}: {expected['rows']:,} rows, "
              f"{path.stat().st_size / 1024:,.0f} KB")
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    export(args.db, args.out)


if __name__ == "__main__":
    main()
