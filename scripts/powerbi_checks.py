"""Expected values for the Power BI measures: powerbi/CHECKS.md.

    python scripts/powerbi_checks.py        # after scripts/export_powerbi.py

Power BI can't run on this machine, so the DAX in powerbi/measures.dax can't
be executed here. Instead, each check query at the end of that file is
mirrored below in SQL over the exported Parquet files only (the same rows
Power BI loads), with the same logic as the DAX: sum the counts, then divide;
leave rows with no cancellation count out of the cancellation base; filter
months by the comparison period; and a rolling window that needs 12 months.
tests/test_powerbi.py checks every value against the dbt metrics models, so
when Power BI's numbers match this file, the model matches the warehouse.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.profile_source import ROOT  # noqa: E402

DATA = ROOT / "powerbi" / "data"
OUT = ROOT / "powerbi" / "CHECKS.md"

# Same floor as dbt_project.yml's ranking_min_flights_per_month; the test
# checks they agree.
FLOOR = 300


def connect(data: Path):
    con = duckdb.connect()
    for path in sorted(data.glob("*.parquet")):
        con.sql(f"create view {path.stem} as select * from read_parquet('{path}')")
    return con


# The DAX measures as SQL. `rows` is a fact table already filtered; the
# expressions are the bodies of the base measures in measures.dax.
FLIGHTS = "sum(sectors_scheduled)"
ON_TIME_ARR = "sum(arrivals_on_time) / nullif(sum(sectors_flown), 0)"
ON_TIME_DEP = "sum(departures_on_time) / nullif(sum(sectors_flown), 0)"
CANCELLED = ("sum(cancellations) / nullif(sum(sectors_scheduled) "
             "filter (where cancellations is not null), 0)")
NAIVE_CANCELLED = "sum(cancellations) / nullif(sum(sectors_scheduled), 0)"


def in_period(alias: str = "f") -> str:
    """Join a fact to the comparison periods by month, like the Period measures."""
    return (f"join dim_comparison_period p on {alias}.month_key "
            "between p.first_month_key and p.last_month_key")


def checks(con) -> list[dict]:
    out = []

    out.append({
        "query": "1. National by period",
        "visual": "Measures: Period Flights Scheduled, Period On-time Arrival %, "
                  "Period On-time Departure %, Period Cancellation %. As a visual: a table "
                  "with `period_label` (sorted by `sort_order`)",
        "headers": ["period_label", "flights", "on-time arrivals", "on-time departures",
                    "cancelled"],
        "kinds": ["text", "flights", "pct", "pct", "pct"],
        "rows": con.sql(f"""
            select p.period_label, {FLIGHTS}, {ON_TIME_ARR}, {ON_TIME_DEP}, {CANCELLED}
            from fct_network_month f {in_period()}
            group by p.period_label, p.sort_order order by p.sort_order""").fetchall(),
    })

    out.append({
        "query": "2. Rolling 12 months",
        "visual": "Measures: Rolling 12m On-time Arrival %, Rolling 12m Cancellation %. "
                  "As a visual: a line chart over `month_start`. Blank before Dec 2004 "
                  "(fewer than 12 months), so the DAX query returns no Nov 2004 row",
        "headers": ["month_label", "on-time arrivals", "cancelled"],
        "kinds": ["text", "pct", "pct"],
        "rows": con.sql(f"""
            with windows as (
                select last.month_key as last_key, last.month_label as last_label,
                       w.month_start, f.*
                from dim_month last
                join dim_month w on w.month_start > last.month_start - interval 12 month
                                and w.month_start <= last.month_start
                join fct_network_month f on f.month_key = w.month_key
                where last.month_key in (200411, 200412, 202303, 202609))
            select last_label,
                   case when count(distinct month_start) = 12 then {ON_TIME_ARR} end,
                   case when count(distinct month_start) = 12 then {CANCELLED} end
            from windows group by last_key, last_label order by last_key""").fetchall(),
    })

    out.append({
        "query": "3. Brand families, FY2018-19 vs latest 12 months",
        "visual": "Measures: Period Flights Scheduled, Period On-time Arrival %, "
                  "Period Cancellation %, Period Meets Floor. As a visual: a matrix with "
                  "`brand_family` on rows and `period_label` on columns",
        "headers": ["brand_family", "period_label", "flights", "on-time arrivals", "cancelled",
                    "meets floor"],
        "kinds": ["text", "text", "flights", "pct", "pct", "bool"],
        "rows": con.sql(f"""
            select a.brand_family, p.period_label, {FLIGHTS}, {ON_TIME_ARR}, {CANCELLED},
                   {FLIGHTS} >= {FLOOR} * any_value(p.months_in_period)
            from fct_network_month f join dim_airline a using (airline_key) {in_period()}
            where p.period_key in ('pre_covid_fy19', 'latest_12m')
            group by a.brand_family, p.period_label, p.sort_order
            order by a.brand_family, p.sort_order""").fetchall(),
    })

    out.append({
        "query": "4. Brisbane - Melbourne by airline, latest 12 months",
        "visual": "Measures: Period Route Flights Scheduled, Period Route On-time Arrival %, "
                  "Period Route Cancellation %. As a visual: a bar chart by `brand_family`, "
                  "filtered to `city_pair_name` = Brisbane - Melbourne and the latest period",
        "headers": ["brand_family", "flights", "on-time arrivals", "cancelled"],
        "kinds": ["text", "flights", "pct", "pct"],
        "rows": con.sql(f"""
            select a.brand_family, {FLIGHTS}, {ON_TIME_ARR}, {CANCELLED}
            from fct_route_month f join dim_airline a using (airline_key)
            join dim_route r using (route_key) {in_period()}
            where r.city_pair_key = 'BNE-MEL' and p.period_key = 'latest_12m'
            group by a.brand_family order by 3 desc""").fetchall(),
    })

    out.append({
        "query": "5. Departing airports above the floor, latest 12 months",
        "visual": "Measures: Period Route Flights Scheduled, Period Route On-time Departure %, "
                  "Period Route Meets Floor. As a visual: a table by `'Departing Port'[port_name]`, "
                  "latest period, with a visual-level filter Period Route Meets Floor = True",
        "headers": ["port_name", "flights", "on-time departures", "meets floor"],
        "kinds": ["text", "flights", "pct", "bool"],
        "rows": con.sql(f"""
            select d.port_name, {FLIGHTS}, {ON_TIME_DEP},
                   {FLIGHTS} >= {FLOOR} * p.months_in_period
            from fct_route_month f join dim_port d on f.departing_port_key = d.port_key
            {in_period()}
            where p.period_key = 'latest_12m'
            group by d.port_name, p.months_in_period
            having {FLIGHTS} >= {FLOOR} * p.months_in_period
            order by 3""").fetchall(),
    })

    out.append({
        "query": "6. The missing-cancellations trap, FY2006-07 routes",
        "visual": "Measure: Route Cancellation %, filtered to `financial_year_label` = "
                  "FY2006-07. The last column is what a plain "
                  "DIVIDE(SUM(cancellations), SUM(sectors_scheduled)) gives: it counts the "
                  "flights with no cancellation figure as if none were cancelled",
        "headers": ["brand_family", "rows missing cancellations", "cancelled",
                    "cancelled if blanks count as zero"],
        "kinds": ["text", "int", "pct", "pct"],
        "rows": con.sql(f"""
            select a.brand_family, count(*) filter (where cancellations is null),
                   {CANCELLED}, {NAIVE_CANCELLED}
            from fct_route_month f join dim_airline a using (airline_key)
            join dim_month m using (month_key)
            where m.financial_year_label = 'FY2006-07'
            group by a.brand_family
            having count(*) filter (where cancellations is null) > 0
            order by a.brand_family""").fetchall(),
    })

    out.append({
        "query": "7. Totals and the volume floor",
        "visual": "Measures: Flights Scheduled and Route Flights Scheduled with no filters "
                  "(the national total is the sum of the airline networks, a little above "
                  "BITRE's published national row; see `audit_national_total` in the warehouse), "
                  "then a count of "
                  "city pairs where Period Route Meets Floor is true in the latest period",
        "headers": ["column", "value"],
        "kinds": ["text", "flights"],
        "rows": [
            ("national flights, all months",
             con.sql(f"select {FLIGHTS} from fct_network_month").fetchone()[0]),
            ("listed-route flights, all months",
             con.sql(f"select {FLIGHTS} from fct_route_month").fetchone()[0]),
            ("city pairs above the floor, latest 12 months",
             con.sql(f"""
                select count(*) from (
                    select r.city_pair_key
                    from fct_route_month f join dim_route r using (route_key) {in_period()}
                    where p.period_key = 'latest_12m'
                    group by r.city_pair_key, p.months_in_period
                    having {FLIGHTS} >= {FLOOR} * p.months_in_period)""").fetchone()[0]),
        ],
    })
    return out


def fmt(value, kind: str) -> str:
    if value is None:
        return "(blank)"
    if kind == "pct":
        return f"{value:.2%}"
    if kind == "bool":
        return "True" if value else "False"
    if kind in ("flights", "int"):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return str(value)


def build(data: Path) -> str:
    con = connect(data)
    sections = []
    for check in checks(con):
        lines = ["| " + " | ".join(check["headers"]) + " |",
                 "|" + "---|" * len(check["headers"])]
        for row in check["rows"]:
            lines.append("| " + " | ".join(fmt(v, k) for v, k in zip(row, check["kinds"])) + " |")
        sections.append(f"### {check['query']}\n\n{check['visual']}.\n\n" + "\n".join(lines))
    return f"""# Power BI check values

*Generated by `scripts/powerbi_checks.py` from the Parquet files in `powerbi/data/`.
Do not edit by hand.*

Once the measures are in the model, run the `EVALUATE` queries at the end of
[`measures.dax`](measures.dax) in DAX query view (or build the visuals described),
and compare. The query results also show their sort columns (`sort_order`,
`month_key`). Rates are shown to two decimal places; Power BI's numbers should
match to the last digit shown. Each value here is computed from the Parquet
files with the same logic as the DAX, and a test checks it against the dbt
metrics models, so a match means the Power BI model agrees with the warehouse.

{chr(10).join(s + chr(10) for s in sections)}"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    args.out.write_text(build(args.data))
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")


if __name__ == "__main__":
    main()
