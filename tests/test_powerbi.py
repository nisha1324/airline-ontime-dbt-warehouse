"""The Power BI export: Parquet files, check values and the DAX file.

Power BI can't run here, so the DAX itself isn't executed. What is tested:
the committed Parquet holds exactly the warehouse rows; every value in
CHECKS.md (SQL over the Parquet with the DAX's logic) equals the dbt metrics
models; and measures.dax is internally consistent (every measure it uses is
defined, the volume floor matches dbt, one check query per CHECKS section).
"""
import json
import re

import duckdb
import pytest

from scripts import export_powerbi, powerbi_checks
from scripts.analyse import floor_per_month
from scripts.download_data import ROOT

POWERBI = ROOT / "powerbi"
STG = "stg_bitre__otp_monthly"


@pytest.fixture(scope="module")
def exported(warehouse, tmp_path_factory):
    db, _ = warehouse
    out = tmp_path_factory.mktemp("powerbi")
    manifest = export_powerbi.export(db, out)
    return out, manifest


@pytest.fixture(scope="module")
def con(warehouse):
    db, _ = warehouse
    return duckdb.connect(str(db), read_only=True)


@pytest.fixture(scope="module")
def check(exported):
    out, _ = exported
    by_title = {c["query"].split(". ", 1)[1]: c for c in powerbi_checks.checks(
        powerbi_checks.connect(out))}

    def rows(title):
        c = by_title[title]
        return [dict(zip(c["headers"], r)) for r in c["rows"]]
    return rows


def test_committed_parquet_is_the_warehouse(con):
    for table, _ in export_powerbi.TABLES:
        path = POWERBI / "data" / f"{table}.parquet"
        for a, b in [(table, f"read_parquet('{path}')"), (f"read_parquet('{path}')", table)]:
            extra = con.sql(f"select count(*) from (select * from {a} except all "
                            f"select * from {b})").fetchone()[0]
            assert extra == 0, f"{path.name} is stale: rerun scripts/export_powerbi.py"


def test_committed_manifest_matches_a_fresh_export(exported):
    _, manifest = exported
    committed = json.loads((POWERBI / "data" / "MANIFEST.json").read_text())
    assert committed == manifest


def test_committed_checks_match_a_fresh_export(exported):
    out, _ = exported
    assert powerbi_checks.build(out) == (POWERBI / "CHECKS.md").read_text(), \
        "powerbi/CHECKS.md is stale: rerun scripts/powerbi_checks.py"


def test_export_refuses_a_file_that_differs(warehouse, tmp_path, monkeypatch):
    db, _ = warehouse
    real = export_powerbi.profile

    def tampered(con, relation):
        result = real(con, relation)
        if relation.startswith("read_parquet") and "dim_port" in relation:
            result["rows"] -= 1
        return result
    monkeypatch.setattr(export_powerbi, "profile", tampered)
    with pytest.raises(SystemExit, match="dim_port.parquet"):
        export_powerbi.export(db, tmp_path)


def test_national_by_period_matches_met_national_month(con, check):
    expected = con.sql("""
        select p.period_label, sum(n.sectors_scheduled),
               sum(n.arrivals_on_time) / sum(n.sectors_flown),
               sum(n.departures_on_time) / sum(n.sectors_flown),
               sum(n.cancellations) / sum(n.cancellation_base)
        from met_national_month n join dim_comparison_period p
          on n.month_key between p.first_month_key and p.last_month_key
        group by p.period_label, p.sort_order order by p.sort_order""").fetchall()
    got = [tuple(r.values()) for r in check("National by period")]
    assert [g[0] for g in got] == [e[0] for e in expected]
    for g, e in zip(got, expected):
        assert g[1:] == pytest.approx(e[1:], abs=1e-12)


def test_rolling_matches_met_national_month(con, check):
    expected = dict(con.sql("""
        select m.month_label, [n.rolling_12m_on_time_arrival_rate, n.rolling_12m_cancellation_rate]
        from met_national_month n join dim_month m using (month_key)
        where month_key in (200411, 200412, 202303, 202609)""").fetchall())
    got = check("Rolling 12 months")
    assert len(got) == 4
    assert got[0]["on-time arrivals"] is None and expected["Nov 2004"] == [None, None]
    for r in got[1:]:
        assert [r["on-time arrivals"], r["cancelled"]] == \
            pytest.approx(expected[r["month_label"]], abs=1e-12)


def test_brands_match_met_brand_period(con, check):
    expected = {(b, p): (s, a, c, k) for b, p, s, a, c, k in con.sql("""
        select brand_family, period_label, sectors_scheduled, on_time_arrival_rate,
               cancellation_rate, is_ranked
        from met_brand_period join dim_comparison_period using (period_key)
        where period_key in ('pre_covid_fy19', 'latest_12m')""").fetchall()}
    got = check("Brand families, FY2018-19 vs latest 12 months")
    assert {(r["brand_family"], r["period_label"]) for r in got} == set(expected)
    for r in got:
        s, a, c, k = expected[(r["brand_family"], r["period_label"])]
        assert (r["flights"], r["on-time arrivals"], r["cancelled"]) == \
            pytest.approx((s, a, c), abs=1e-12)
        assert r["meets floor"] == k


def test_same_route_matches_met_city_pair_brand_period(con, check):
    expected = {b: (s, a, c) for b, s, a, c in con.sql("""
        select brand_family, sectors_scheduled, on_time_arrival_rate, cancellation_rate
        from met_city_pair_brand_period
        where period_key = 'latest_12m' and city_pair_key = 'BNE-MEL'""").fetchall()}
    got = check("Brisbane - Melbourne by airline, latest 12 months")
    assert {r["brand_family"] for r in got} == set(expected)
    for r in got:
        assert (r["flights"], r["on-time arrivals"], r["cancelled"]) == \
            pytest.approx(expected[r["brand_family"]], abs=1e-12)


def test_airports_match_met_departing_port_period(con, check):
    expected = con.sql("""
        select port_name, sectors_scheduled, on_time_departure_rate
        from met_departing_port_period
        where period_key = 'latest_12m' and is_ranked
        order by on_time_departure_rate""").fetchall()
    got = check("Departing airports above the floor, latest 12 months")
    assert [r["port_name"] for r in got] == [e[0] for e in expected]
    for r, e in zip(got, expected):
        assert (r["flights"], r["on-time departures"]) == pytest.approx(e[1:], abs=1e-12)
        assert r["meets floor"] is True


def test_cancellation_trap_matches_staging(con, check):
    # Straight from staging rows and the brand seed, not the facts.
    expected = {b: (n, c, z) for b, n, c, z in con.sql(f"""
        select b.brand_family, count(*) filter (where s.cancellations is null),
               sum(s.cancellations) / sum(s.sectors_scheduled)
                   filter (where s.cancellations is not null),
               sum(s.cancellations) / sum(s.sectors_scheduled)
        from {STG} s join airline_brands b using (airline_name)
        where s.row_grain = 'route_airline'
          and s.month_start between date '2006-07-01' and date '2007-06-01'
        group by 1 having count(*) filter (where s.cancellations is null) > 0""").fetchall()}
    got = check("The missing-cancellations trap, FY2006-07 routes")
    assert sum(r["rows missing cancellations"] for r in got) == 316
    for r in got:
        n, c, z = expected[r["brand_family"]]
        assert r["rows missing cancellations"] == n
        assert r["cancelled"] == pytest.approx(c, abs=1e-12)
        assert r["cancelled if blanks count as zero"] == pytest.approx(z, abs=1e-12)
        assert r["cancelled"] > r["cancelled if blanks count as zero"]


def test_totals_match_the_metrics_models(con, check):
    got = {r["column"]: r["value"] for r in check("Totals and the volume floor")}
    national, route, ranked = con.sql(f"""
        select (select sum(sectors_scheduled) from met_national_month),
               (select sum(sectors_scheduled) from {STG} where row_grain = 'route_airline'),
               (select count(*) from met_city_pair_period
                where period_key = 'latest_12m' and is_ranked)""").fetchone()
    assert got["national flights, all months"] == pytest.approx(national, abs=1e-6)
    assert got["listed-route flights, all months"] == pytest.approx(route, abs=1e-6)
    assert got["city pairs above the floor, latest 12 months"] == ranked


# ---- measures.dax, checked statically --------------------------------------

DAX = (POWERBI / "measures.dax").read_text()
CODE = re.sub(r"//[^\n]*", "", DAX)   # comments out
DEFINED = re.findall(r"MEASURE\s+('[^']+'|\w+)\[([^\]]+)\]", CODE)


def test_every_measure_used_is_defined_once():
    names = [m for _, m in DEFINED]
    assert len(names) == len(set(names)), "a measure is defined twice"
    # [Name] not preceded by a table name is a measure (or a query column).
    used = set(re.findall(r"(?<![\w'\]])\[([^\]]+)\]", CODE))
    query_columns = set(re.findall(r'"([^"]+)"\s*,', CODE))
    assert used - set(names) - query_columns == set()


def test_dax_tables_exist_in_the_export():
    exported = {t for t, _ in export_powerbi.TABLES} - {"dim_port"}
    tables = {t.strip("'") for t in re.findall(r"('[^']+'|\b[a-z_]+\b)\[", CODE)}
    assert tables == exported | {"Departing Port"}
    manifest = json.loads((POWERBI / "data" / "MANIFEST.json").read_text())["tables"]
    for table, column in re.findall(r"\b([a-z_]+)\[([a-z_]+)\]", CODE):
        assert column in {c["name"] for c in manifest[table]["columns"]}, f"{table}[{column}]"


def test_dax_rules_match_dbt():
    assert floor_per_month() == powerbi_checks.FLOOR
    assert set(re.findall(r"(\d+) \* \[Period Months\]", CODE)) == {str(floor_per_month())}
    assert "= BLANK" not in CODE, "use ISBLANK: in DAX 0 = BLANK() is true"
    # One EVALUATE per CHECKS.md section, in the same order.
    evaluates = re.findall(r"// (\d)\. ([^\n]+)\nEVALUATE", DAX)
    sections = re.findall(r"^### (\d)\. (.+)$", (POWERBI / "CHECKS.md").read_text(), re.M)
    assert [n for n, _ in evaluates] == [n for n, _ in sections]
    for (_, dax_title), (_, md_title) in zip(evaluates, sections):
        assert md_title.startswith(dax_title.split(" (")[0])


def test_guide_row_counts_match_the_manifest():
    manifest = json.loads((POWERBI / "data" / "MANIFEST.json").read_text())["tables"]
    guide = (POWERBI / "POWERBI_GUIDE.md").read_text()
    loads = re.findall(r"^\| `[^`]+` \| `(\w+)\.parquet` \| ([\d,]+) \|", guide, re.M)
    assert {t for t, _ in loads} == set(manifest)
    for table, rows in loads:
        assert int(rows.replace(",", "")) == manifest[table]["rows"], table


def test_readme_counts_the_measures():
    readme = (ROOT / "README.md").read_text()
    assert set(re.findall(r"(\d+) DAX measures", readme)) == {str(len(DEFINED))}
