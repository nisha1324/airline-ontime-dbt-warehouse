"""Describe the star schema and its reconciliations: results/STAR_SCHEMA.md.

    python scripts/build.py && python scripts/describe_schema.py

Reads data/warehouse.duckdb (built by dbt). Like the source profile, every
number comes from a query below and the output is deterministic.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.profile_source import DB, ROOT, STG, fmt, scalar, table  # noqa: E402

OUT = ROOT / "results" / "STAR_SCHEMA.md"

TABLES = [
    ("fct_route_month", "fact", "airline × directional route × month",
     "month_key, airline_key, route_key, departing_port_key, arriving_port_key"),
    ("fct_network_month", "fact", "airline × month (whole network)",
     "month_key, airline_key"),
    ("dim_airline", "dimension", "airline (cleaned name)", "airline_key"),
    ("dim_route", "dimension", "directional route", "route_key"),
    ("dim_port", "dimension", "port, role-played as departing and arriving", "port_key"),
    ("dim_month", "dimension", "calendar month", "month_key"),
    ("audit_national_total", "audit", "month", "month_key"),
]


def build_report(con) -> str:
    first = scalar(con, "select month_label from dim_month order by month_key limit 1")
    last = scalar(con, "select month_label from dim_month order by month_key desc limit 1")

    rows = []
    for name, kind, grain, keys in TABLES:
        n = scalar(con, f"select count(*) from {name}")
        rows.append(f"| `{name}` | {kind} | {grain} | {n:,} | {keys} |")

    route_fact = scalar(con, "select sum(sectors_scheduled) from fct_route_month")
    route_staged = scalar(con, f"""
        select sum(sectors_scheduled) from {STG} where row_grain = 'route_airline'""")
    network_fact = scalar(con, "select sum(sectors_scheduled) from fct_network_month")
    published = scalar(con, f"""
        select sum(sectors_scheduled) from {STG} where row_grain = 'network_all_airlines'""")
    n_months = scalar(con, "select count(*) from audit_national_total")
    n_gaps = scalar(con, "select count(*) from audit_national_total where has_gap")
    n_explained = scalar(con, """
        select count(*) from audit_national_total where gap_airline is not null""")
    max_gap_share = scalar(con, """
        select max(scheduled_gap / published_scheduled) from audit_national_total""")
    max_otp_move = scalar(con, """
        select max(abs(warehouse_on_time_rate - published_on_time_rate))
        from audit_national_total""")

    route_months = scalar(con, f"""
        select count(*) from {STG} where row_grain = 'route_all_airlines'""")
    route_mismatch = scalar(con, f"""
        with rebuilt as (
            select month_key, route_key,
                   sum(sectors_scheduled) as sectors_scheduled,
                   sum(sectors_flown) as sectors_flown,
                   sum(cancellations) as cancellations,
                   sum(arrivals_on_time) as arrivals_on_time,
                   sum(departures_on_time) as departures_on_time
            from fct_route_month group by all
        ),
        published as (
            select (year(s.month_start) * 100 + month(s.month_start))::integer as month_key,
                   r.route_key, s.sectors_scheduled, s.sectors_flown, s.cancellations,
                   s.arrivals_on_time, s.departures_on_time
            from {STG} s join dim_route r using (route_name)
            where s.row_grain = 'route_all_airlines'
        )
        select count(*) from published full join rebuilt using (month_key, route_key)
        where round(published.sectors_scheduled, 6) is distinct from round(rebuilt.sectors_scheduled, 6)
           or round(published.sectors_flown, 6) is distinct from round(rebuilt.sectors_flown, 6)
           or round(published.cancellations, 6) is distinct from round(rebuilt.cancellations, 6)
           or round(published.arrivals_on_time, 6) is distinct from round(rebuilt.arrivals_on_time, 6)
           or round(published.departures_on_time, 6) is distinct from round(rebuilt.departures_on_time, 6)""")

    gap_table = table(con, """
        select d.month_label, a.published_scheduled, a.warehouse_scheduled, a.scheduled_gap,
               printf('%.1f%%', 100 * a.scheduled_gap / a.published_scheduled),
               printf('%.2f%%', 100 * a.published_on_time_rate),
               printf('%.2f%%', 100 * a.warehouse_on_time_rate),
               coalesce(a.gap_airline || ' (first reported ' ||
                        strftime(al.first_month_reported, '%b %Y') || ')', 'no single airline')
        from audit_national_total a
        join dim_month d using (month_key)
        left join dim_airline al on al.airline_name = a.gap_airline
        where a.has_gap
        order by a.month_key""",
        ["Month", "Published national row", "Warehouse (sum of airlines)", "Gap",
         "Gap %", "On time, published", "On time, warehouse", "Gap = network of"])

    family_table = table(con, """
        select brand_family,
               string_agg(airline_name, ' → ' order by first_month_reported, airline_name),
               strftime(min(first_month_reported), '%b %Y'),
               strftime(max(last_month_reported), '%b %Y'),
               any_value(lineage_source) filter (where lineage_source is not null)
        from dim_airline
        group by brand_family
        having count(*) > 1
        order by brand_family""",
        ["Brand family", "Airlines (in order of first report)", "From", "To", "Evidence"])

    airline_table = table(con, """
        select airline_name, brand_family,
               strftime(first_month_reported, '%b %Y'), strftime(last_month_reported, '%b %Y'),
               months_reported, routes_listed,
               case when is_reporting_now then 'yes' else '' end
        from dim_airline
        order by first_month_reported, airline_name""",
        ["Airline", "Brand family", "First month", "Last month", "Months", "Routes listed",
         "Reporting now"])

    route_mix = table(con, """
        select case when is_capital_to_capital then 'Capital to capital'
                    when is_intrastate then 'Within one state'
                    else 'Interstate, not capital to capital' end,
               count(*), count(distinct city_pair_key)
        from dim_route group by 1 order by 2 desc""",
        ["Route type", "Directional routes", "City pairs"])

    ports_by_state = table(con, """
        select state, count(*), string_agg(port_name, ', ' order by port_name)
        from dim_port group by state order by count(*) desc, state""",
        ["State", "Ports", "Names"])

    return f"""# Star schema

*Generated by `scripts/describe_schema.py` from `data/warehouse.duckdb`. Do not edit by hand.*

{first} to {last}. Two facts at their own grains share the airline and month dimensions.
Keys are readable and stable across rebuilds: `yyyymm` for months, IATA codes for ports and
routes, and a slug of the name for airlines.

## Tables

| Table | Type | Grain (one row per…) | Rows | Keys |
|---|---|---|---|---|
{chr(10).join(rows)}

## Reconciliation

| Check | Result |
|---|---|
| `fct_route_month` holds every airline-on-route row | {fmt(route_fact)} flights scheduled = {fmt(route_staged)} in staging |
| Route totals rebuilt from airline rows vs BITRE's published route totals | equal in {route_months - route_mismatch:,} of {route_months:,} route-months |
| National total = sum of `fct_network_month` vs the published national row | {fmt(network_fact)} vs {fmt(published)} flights; equal in {n_months - n_gaps} of {n_months} months |

Route totals are not stored: "all airlines on a route" is a `SUM` over `fct_route_month`,
so a route's total always equals its airline breakdown. The {route_mismatch} route-months where
BITRE's own total disagrees are listed in [`SOURCE_PROFILE.md`](SOURCE_PROFILE.md).

## Which national total?

The warehouse's national total is the **sum of the airline network rows**, not BITRE's
published national row. BITRE defines the industry total as all services operated by the
reporting airlines, yet in {n_explained} of the {n_gaps} months below the published row leaves out the
whole network of an airline in its first months of reporting. Summing the airline rows also
means a report's grand total always equals the sum of its airline bars.

{gap_table}

The largest gap is {100 * max_gap_share:.1f}% of flights and moves the national on-time rate
by at most {100 * max_otp_move:.2f} percentage points. A dbt test fails the build if a future
release opens a gap over 3% or moves the on-time rate by more than 0.5 points, so the choice
gets revisited rather than silently carried on.

## Airlines and brand history

Renamed or merged airlines keep their own rows, as BITRE reported them. `brand_family` chains
the ones that are one continuing operation, so a long trend can follow them:

{family_table}

Skytrans (to Jun 2025) and Skytrans Australia (from Jan 2026) are **not** chained: there is a
six-month gap between them and no published source links them.

{airline_table}

Airlines with 0 routes listed report only a network total.

## Routes and ports

{route_mix}

{ports_by_state}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    con = duckdb.connect(str(args.db), read_only=True)
    report = build_report(con)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")


if __name__ == "__main__":
    main()
