"""The star schema: keys, calendar logic, the national-total decision and the
generated schema report. Expected values were worked out by hand from the
source rows (see results/SOURCE_PROFILE.md) rather than copied from the
models' output."""
import subprocess
import sys

import duckdb
import pytest

from scripts.download_data import ROOT

MARTS = ["dim_month", "dim_port", "dim_route", "dim_airline",
         "fct_route_month", "fct_network_month", "audit_national_total"]


@pytest.fixture(scope="module")
def con(warehouse):
    db, _ = warehouse
    return duckdb.connect(str(db), read_only=True)


@pytest.mark.parametrize("month_key, label, fy, fy_month", [
    (200401, "FY2003-04", 2004, 7),    # first month in the data: January
    (200406, "FY2003-04", 2004, 12),   # June closes the financial year
    (200407, "FY2004-05", 2005, 1),    # July opens the next one
    (202512, "FY2025-26", 2026, 6),
    (202609, "FY2026-27", 2027, 3),    # latest month
])
def test_financial_year_runs_july_to_june(con, month_key, label, fy, fy_month):
    row = con.sql(f"""select financial_year_label, financial_year, financial_month_num
                      from dim_month where month_key = {month_key}""").fetchone()
    assert row == (label, fy, fy_month)


def test_month_dimension_covers_every_month_once(con):
    n, first, last = con.sql(
        "select count(*), min(month_key), max(month_key) from dim_month").fetchone()
    # Jan 2004 .. Sep 2026 inclusive = 22 years and 9 months
    assert (n, first, last) == (22 * 12 + 9, 200401, 202609)


def test_route_keys_use_iata_codes_both_ways(con):
    rows = dict(con.sql("""select route_name, route_key || ' ' || city_pair_key
                           from dim_route
                           where route_name in ('Sydney-Melbourne', 'Melbourne-Sydney',
                                                'Cairns-Brisbane')""").fetchall())
    assert rows == {
        "Sydney-Melbourne": "SYD-MEL MEL-SYD",
        "Melbourne-Sydney": "MEL-SYD MEL-SYD",
        "Cairns-Brisbane": "CNS-BNE BNE-CNS",
    }


def test_route_flags(con):
    rows = dict(con.sql("""select route_key, (is_intrastate, is_capital_to_capital)
                           from dim_route
                           where route_key in ('SYD-MEL', 'BNE-CNS', 'CBR-SYD', 'OOL-SYD')
                        """).fetchall())
    assert rows == {
        "SYD-MEL": (False, True),
        "BNE-CNS": (True, False),
        "CBR-SYD": (False, True),    # ACT and NSW are different jurisdictions
        "OOL-SYD": (False, False),   # Gold Coast airport is in Queensland
    }


def test_facts_keep_their_grains_apart(con):
    # Figures from the source profile: 87,176 airline-on-route rows carrying
    # 8,681,901 scheduled flights, and 1,918 airline-network rows.
    assert con.sql("""select count(*), sum(sectors_scheduled)
                      from fct_route_month""").fetchone() == (87_176, 8_681_901)
    assert con.sql("select count(*) from fct_network_month").fetchone()[0] == 1_918


def test_national_total_is_the_sum_of_airline_networks(con):
    published, warehouse = con.sql("""
        select sum(published_scheduled), sum(warehouse_scheduled)
        from audit_national_total""").fetchone()
    assert published == 11_495_634.5
    # the 5 gaps in SOURCE_PROFILE.md add up to 3,671 flights
    assert warehouse - published == pytest.approx(3_671)
    gaps = con.sql("""select month_key, gap_airline from audit_national_total
                      where has_gap order by month_key""").fetchall()
    assert gaps == [(200603, None), (202305, "Skytrans"), (202403, "Hinterland"),
                    (202404, "Hinterland"), (202405, "Hinterland")]


def test_brand_families_chain_renames_without_overlap_or_gaps(con):
    # Rex: Regional Express to Jun 2021, then Rex Airlines from Jul 2021.
    months = con.sql("""
        select count(*), count(distinct month_key), min(month_key), max(month_key)
        from fct_network_month join dim_airline using (airline_key)
        where brand_family = 'Rex'""").fetchone()
    assert months == (273, 273, 200401, 202609)


def test_unlinked_airlines_stay_separate(con):
    families = dict(con.sql("""select airline_name, brand_family from dim_airline
                               where airline_name like 'Skytrans%'""").fetchall())
    assert families == {"Skytrans": "Skytrans", "Skytrans Australia": "Skytrans Australia"}


def test_star_join_loses_no_rows(con):
    # Joining the route fact to every dimension (as a BI tool would) keeps
    # every row exactly once.
    n = con.sql("""
        select count(*)
        from fct_route_month f
        join dim_month m using (month_key)
        join dim_airline a using (airline_key)
        join dim_route r using (route_key)
        join dim_port dep on dep.port_key = f.departing_port_key
        join dim_port arr on arr.port_key = f.arriving_port_key""").fetchone()[0]
    assert n == 87_176


@pytest.mark.parametrize("table", MARTS)
def test_marts_open_from_another_folder(warehouse, tmp_path, monkeypatch, table):
    db, _ = warehouse
    monkeypatch.chdir(tmp_path)
    con = duckdb.connect(str(db), read_only=True)
    assert con.sql(f"select count(*) from {table}").fetchone()[0] > 0


def test_committed_schema_report_matches_a_fresh_build(warehouse, tmp_path):
    db, _ = warehouse
    out = tmp_path / "STAR_SCHEMA.md"
    subprocess.run([sys.executable, "scripts/describe_schema.py", "--db", str(db),
                    "--out", str(out)], cwd=ROOT, check=True, capture_output=True)
    committed = (ROOT / "results" / "STAR_SCHEMA.md").read_text()
    assert out.read_text() == committed, "results/STAR_SCHEMA.md is stale: rerun describe_schema.py"
