"""The metrics layer and the analysis report. The cross-checks recompute rates
straight from staging rows (by row grain and route name), not from the facts
or dimensions, so a wrong join or key in the metrics models shows up here."""
import subprocess
import sys

import duckdb
import pytest

from scripts.analyse import floor_per_month, spearman
from scripts.download_data import ROOT

STG = "stg_bitre__otp_monthly"


@pytest.fixture(scope="module")
def con(warehouse):
    db, _ = warehouse
    return duckdb.connect(str(db), read_only=True)


def test_periods(con):
    rows = con.sql("""select period_key, first_month_key, last_month_key, months_in_period
                      from dim_comparison_period order by sort_order""").fetchall()
    assert rows == [
        ("long_run_pre_covid", 200407, 201906, 180),   # 15 financial years
        ("pre_covid_fy19", 201807, 201906, 12),
        ("latest_12m", 202510, 202609, 12),           # snapshot ends Sep 2026
    ]


def test_national_latest_12m_matches_staging(con):
    expected = con.sql(f"""
        select sum(arrivals_on_time) / sum(sectors_flown),
               sum(cancellations) / sum(sectors_scheduled)
        from {STG}
        where row_grain = 'network_airline'
          and month_start between date '2025-10-01' and date '2026-09-01'""").fetchone()
    rolling = con.sql("""
        select rolling_12m_on_time_arrival_rate, rolling_12m_cancellation_rate
        from met_national_month where month_key = 202609""").fetchone()
    assert rolling == pytest.approx(expected, abs=1e-12)


def test_rolling_rate_is_a_ratio_of_sums_not_an_average(con):
    ratio, average = con.sql("""
        select rolling_12m_on_time_arrival_rate,
               avg(on_time_arrival_rate) over (order by month_key rows between 11 preceding
                                               and current row)
        from met_national_month qualify month_key = 202609""").fetchone()
    by_hand = con.sql("""
        select sum(arrivals_on_time) / sum(sectors_flown) from met_national_month
        where month_key between 202510 and 202609""").fetchone()[0]
    assert ratio == pytest.approx(by_hand, abs=1e-12)
    assert ratio != pytest.approx(average, abs=1e-9)


def test_departing_port_matches_route_names(con):
    # "Melbourne-..." routes in staging, independent of dim_route / dim_port keys.
    expected = con.sql(f"""
        select sum(sectors_scheduled), sum(departures_on_time) / sum(sectors_flown)
        from {STG}
        where row_grain = 'route_airline' and route_name like 'Melbourne-%'
          and month_start between date '2025-10-01' and date '2026-09-01'""").fetchone()
    got = con.sql("""
        select sectors_scheduled, on_time_departure_rate from met_departing_port_period
        where period_key = 'latest_12m' and port_key = 'MEL'""").fetchone()
    assert got == pytest.approx(expected, abs=1e-12)


def test_city_pair_adds_both_directions(con):
    expected = con.sql(f"""
        select sum(sectors_scheduled), sum(arrivals_on_time) / sum(sectors_flown)
        from {STG}
        where row_grain = 'route_airline'
          and route_name in ('Melbourne-Sydney', 'Sydney-Melbourne')
          and month_start between date '2025-10-01' and date '2026-09-01'""").fetchone()
    got = con.sql("""
        select sectors_scheduled, on_time_arrival_rate from met_city_pair_period
        where period_key = 'latest_12m' and city_pair_key = 'MEL-SYD'""").fetchone()
    assert got == pytest.approx(expected, abs=1e-12)


def test_missing_cancellations_leave_the_long_run_denominator(con):
    # 316 route rows have no cancellation count (results/SOURCE_PROFILE.md),
    # all inside the long-run window and none in the two recent windows.
    by_period = dict(con.sql("""select period_key, sum(rows_missing_cancellations)
                                from met_city_pair_period group by 1""").fetchall())
    assert by_period == {"long_run_pre_covid": 316, "pre_covid_fy19": 0, "latest_12m": 0}
    base, scheduled, missing_scheduled = con.sql(f"""
        select (select sum(cancellation_base) from met_city_pair_period
                where period_key = 'long_run_pre_covid'),
               sum(sectors_scheduled),
               sum(sectors_scheduled) filter (where cancellations is null)
        from {STG}
        where row_grain = 'route_airline'
          and month_start between date '2004-07-01' and date '2019-06-01'""").fetchone()
    assert missing_scheduled > 0
    assert base == pytest.approx(scheduled - missing_scheduled, abs=1e-6)


def test_ranking_flag_follows_the_dbt_var(con):
    floor = floor_per_month()
    for model in ["met_brand_period", "met_city_pair_period",
                  "met_city_pair_brand_period", "met_departing_port_period"]:
        ranked_min, unranked_max = con.sql(f"""
            select min(sectors_scheduled / months_in_period) filter (where is_ranked),
                   max(sectors_scheduled / months_in_period) filter (where not is_ranked)
            from {model}""").fetchone()
        assert ranked_min >= floor, model
        assert unranked_max is None or unranked_max < floor, model


def test_spearman_handles_ties():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # ties get average ranks: x ranks 1, 2.5, 2.5, 4
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833, abs=1e-6)


def test_committed_metrics_report_and_charts_match_a_fresh_build(warehouse, tmp_path):
    db, _ = warehouse
    out = tmp_path / "METRICS.md"
    subprocess.run([sys.executable, "scripts/analyse.py", "--db", str(db), "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    committed = ROOT / "results"
    assert out.read_text() == (committed / "METRICS.md").read_text(), \
        "results/METRICS.md is stale: rerun scripts/analyse.py"
    charts = sorted(p.name for p in (committed / "charts").glob("*.png"))
    assert charts == sorted(p.name for p in (tmp_path / "charts").glob("*.png"))
    for name in charts:
        assert (tmp_path / "charts" / name).read_bytes() == \
            (committed / "charts" / name).read_bytes(), f"results/charts/{name} is stale"
