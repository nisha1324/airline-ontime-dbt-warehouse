"""Answer the business questions from the metrics layer: results/METRICS.md + charts.

    python scripts/build.py && python scripts/analyse.py

Reads the dbt metrics models in data/warehouse.duckdb. Every rate comes from
those models (defined once in warehouse/macros/otp_metrics.sql); this script
only selects, ranks and draws. The report and the PNGs are deterministic, so
a test can rebuild them and compare.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import matplotlib
import yaml

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.profile_source import DB, ROOT, scalar  # noqa: E402

OUT = ROOT / "results" / "METRICS.md"
CHARTS = "charts"

# dataviz reference palette, light mode. Slots 1-3 validate all-pairs
# (scripts/validate_palette.js), so up to three series share a chart.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
INK, INK_2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#fcfcfb"
# Airlines keep one colour on every chart (colour follows the entity).
BRAND_COLOR = {"Qantas": SERIES[0], "Virgin Australia": SERIES[1], "Jetstar": SERIES[2]}

TOP_CITY_PAIRS = 5     # busiest city pairs for the same-route airline comparison
LOW_FLOOR = 100        # flights a month: the sensitivity check's lower floor


def floor_per_month() -> int:
    project = yaml.safe_load((ROOT / "warehouse" / "dbt_project.yml").read_text())
    return int(project["vars"]["ranking_min_flights_per_month"])


def word(a: float, b: float, lower: str = "below", higher: str = "above") -> str:
    return lower if a < b else higher


def pct(x: float | None, places: int = 1) -> str:
    return "–" if x is None else f"{100 * x:.{places}f}%"


def pts(x: float, places: int = 1) -> str:
    return f"{100 * x:+.{places}f} pts"


def md_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation with average ranks for ties (no scipy needed)."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / var


# ---------------------------------------------------------------- charts

def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def new_figure(w: float, h: float, nrows: int = 1, ncols: int = 1, **kw):
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h), facecolor=SURFACE, **kw)
    return fig, axes


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # No timestamp or software tag in the PNG, so reruns are byte-identical.
    fig.savefig(path, dpi=150, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def chart_national(con, path: Path, long_run: dict) -> None:
    rows = con.sql("""
        select month_start, rolling_12m_on_time_arrival_rate, rolling_12m_cancellation_rate
        from met_national_month
        where rolling_12m_on_time_arrival_rate is not null
        order by month_key""").fetchall()
    months = [r[0] for r in rows]
    fig, (top, bottom) = new_figure(9, 6.2, 2, 1, sharex=True,
                                    gridspec_kw={"height_ratios": [3, 2], "hspace": 0.12})
    for ax, idx, key, label in ((top, 1, "on_time_arrival_rate", "On-time arrivals"),
                                (bottom, 2, "cancellation_rate", "Cancellations")):
        style(ax)
        values = [100 * r[idx] for r in rows]
        ax.plot(months, values, color=SERIES[0], linewidth=2)
        ref = 100 * long_run[key]
        ax.axhline(ref, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
        # Both labels sit right of the line's end; the one that is lower goes below.
        latest_low = values[-1] < ref
        ax.annotate(f"avg {ref:.1f}%", (months[-1], ref), xytext=(6, 4 if latest_low else -4),
                    textcoords="offset points", color=INK_2, fontsize=8.5,
                    va="bottom" if latest_low else "top")
        ax.annotate(f"{values[-1]:.1f}%", (months[-1], values[-1]), xytext=(6, -4 if latest_low else 4),
                    textcoords="offset points", color=INK, fontsize=9, fontweight="bold",
                    va="top" if latest_low else "bottom")
        ax.set_ylabel(f"{label}, % (12 months)", color=INK_2, fontsize=9)
    trough = min(range(len(rows)), key=lambda i: rows[i][1])
    top.annotate(f"12 months to {months[trough]:%b %Y}: {100 * rows[trough][1]:.1f}%",
                 (months[trough], 100 * rows[trough][1]), xytext=(-150, -4),
                 textcoords="offset points", color=INK_2, fontsize=8.5,
                 arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8})
    peak = max(range(len(rows)), key=lambda i: rows[i][2])
    bottom.annotate(f"12 months to {months[peak]:%b %Y}: {100 * rows[peak][2]:.1f}%",
                    (months[peak], 100 * rows[peak][2]), xytext=(-175, -6),
                    textcoords="offset points", color=INK_2, fontsize=8.5,
                    arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8})
    bottom.xaxis.set_major_locator(mdates.YearLocator(2))
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    bottom.set_xlim(months[0], months[-1].replace(year=months[-1].year + 1))
    fig.suptitle("Australian domestic flights: on-time arrivals and cancellations, rolling 12 months",
                 x=0.07, ha="left", color=INK, fontsize=11.5, fontweight="bold")
    fig.text(0.07, 0.915, "All reporting airlines, whole networks. Dashed line: FY2004-05 to FY2018-19 average. "
             "Source: BITRE, data.gov.au (CC BY 3.0 AU).",
             color=INK_2, fontsize=8.5)
    fig.subplots_adjust(left=0.08, right=0.9, top=0.89, bottom=0.06)
    save(fig, path)


def chart_dumbbell(path: Path, brands: list[tuple], title: str) -> None:
    """brands: (name, fy19_arrival, latest_arrival, fy19_cancel, latest_cancel)."""
    fig, (left, right) = new_figure(9, 3.6, 1, 2, sharey=True,
                                    gridspec_kw={"wspace": 0.08, "width_ratios": [3, 2]})
    names = [b[0] for b in brands]
    ys = list(range(len(brands)))[::-1]
    for ax, i0, i1, label in ((left, 1, 2, "On-time arrivals, %"),
                              (right, 3, 4, "Cancellations, %")):
        style(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        for y, b in zip(ys, brands):
            a, c = 100 * b[i0], 100 * b[i1]
            ax.plot([a, c], [y, y], color="#c9c8c2", linewidth=2, zorder=1)
            ax.scatter([a], [y], s=46, facecolor=SURFACE, edgecolor=SERIES[0], linewidth=1.8, zorder=2)
            ax.scatter([c], [y], s=46, color=SERIES[0], edgecolor=SURFACE, linewidth=1.5, zorder=3)
            ax.annotate(f"{c:.1f}", (c, y), xytext=(0, 7), textcoords="offset points",
                        ha="center", color=INK, fontsize=8.5)
        ax.set_xlabel(label, color=INK_2, fontsize=9)
    left.set_yticks(ys, names)
    lo = min(min(b[1], b[2]) for b in brands) * 100
    hi = max(max(b[1], b[2]) for b in brands) * 100
    left.set_xlim(lo - 3, hi + 3)
    right.set_xlim(0, max(max(b[3], b[4]) for b in brands) * 100 + 1)
    left.set_ylim(-0.6, len(brands) - 0.3)
    handles = [plt.Line2D([], [], marker="o", linestyle="", markerfacecolor=SURFACE,
                          markeredgecolor=SERIES[0], markersize=7, label="FY2018-19"),
               plt.Line2D([], [], marker="o", linestyle="", color=SERIES[0], markersize=7,
                          label="Latest 12 months (labelled)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.16, 0.9), ncol=2,
               frameon=False, fontsize=8.5, labelcolor=INK_2)
    fig.suptitle(title, x=0.16, ha="left", color=INK, fontsize=11.5, fontweight="bold")
    fig.subplots_adjust(left=0.16, right=0.98, top=0.78, bottom=0.15)
    save(fig, path)


def chart_same_route(path: Path, pairs: list[str], rows: list[tuple], title: str) -> None:
    """rows: (city_pair, brand, arrival_rate, cancellation_rate) for ranked brands."""
    fig, ax = new_figure(9, 0.62 * len(pairs) + 1.6)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ys = {p: y for y, p in enumerate(pairs[::-1])}
    for pair in pairs:
        vals = [100 * r[2] for r in rows if r[0] == pair]
        ax.plot([min(vals), max(vals)], [ys[pair]] * 2, color="#c9c8c2", linewidth=2, zorder=1)
    for brand, color in BRAND_COLOR.items():
        pts_ = [(100 * r[2], ys[r[0]]) for r in rows if r[1] == brand]
        ax.scatter([p[0] for p in pts_], [p[1] for p in pts_], s=60, color=color,
                   edgecolor=SURFACE, linewidth=1.5, zorder=3, label=brand)
    ax.set_yticks(list(ys.values()), list(ys.keys()))
    ax.set_xlabel("On-time arrivals, % (latest 12 months)", color=INK_2, fontsize=9)
    ax.set_ylim(-0.6, len(pairs) - 0.4)
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.1), ncol=3, frameon=False,
              fontsize=8.5, labelcolor=INK_2, handletextpad=0.3)
    fig.suptitle(title, x=0.2, ha="left", color=INK, fontsize=11.5, fontweight="bold")
    fig.subplots_adjust(left=0.2, right=0.97, top=0.84, bottom=0.17)
    save(fig, path)


def chart_city_pairs(path: Path, rows: list[tuple], listed_rate: float, title: str) -> None:
    """rows: (city_pair, arrival_rate) sorted worst first."""
    fig, ax = new_figure(8, 0.24 * len(rows) + 1.5)
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ys = list(range(len(rows)))[::-1]
    vals = [100 * r[1] for r in rows]
    lo = min(vals) - 2
    ax.hlines(ys, lo, max(vals) + 2.5, color=GRID, linewidth=0.8, zorder=0)
    ax.scatter(vals, ys, s=34, color=SERIES[0], edgecolor=SURFACE, linewidth=1, zorder=3)
    ax.axvline(100 * listed_rate, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(f"All listed routes: {100 * listed_rate:.1f}%", (100 * listed_rate, len(rows) - 0.4),
                xytext=(4, 0), textcoords="offset points", color=INK_2, fontsize=8.5, va="bottom")
    for y, v in zip(ys, vals):
        # A surface-coloured box keeps the reference line from striking through a label.
        ax.annotate(f"{v:.1f}", (v, y), xytext=(5, 0), textcoords="offset points",
                    va="center", color=INK_2, fontsize=7.5, zorder=4,
                    bbox={"boxstyle": "square,pad=0.1", "facecolor": SURFACE, "edgecolor": "none"})
    ax.set_yticks(ys, [r[0] for r in rows], fontsize=8.5)
    ax.set_xlim(lo, max(vals) + 2.5)
    ax.set_ylim(-0.8, len(rows) + 0.4)
    ax.set_xlabel("On-time arrivals, %", color=INK_2, fontsize=9)
    fig.suptitle(title, x=0.03, ha="left", color=INK, fontsize=11.5, fontweight="bold")
    fig.subplots_adjust(left=0.3, right=0.97, top=1 - 0.75 / fig.get_figheight(),
                        bottom=0.55 / fig.get_figheight())
    save(fig, path)


# ---------------------------------------------------------------- report

def build(con, out: Path) -> str:
    charts = out.parent / CHARTS
    floor_note = f"at least {floor_per_month()}"
    periods = {k: (label, first, last) for k, label, first, last in con.sql("""
        select period_key, period_label, strftime(first_month, '%b %Y'), strftime(last_month, '%b %Y')
        from dim_comparison_period""").fetchall()}
    latest_label = periods["latest_12m"][0]

    # National ------------------------------------------------------------
    national = {}
    for key, *vals in con.sql("""
            select p.period_key, sum(n.sectors_scheduled),
                   sum(n.arrivals_on_time) / sum(n.sectors_flown),
                   sum(n.departures_on_time) / sum(n.sectors_flown),
                   sum(n.cancellations) / sum(n.cancellation_base)
            from met_national_month n
            join dim_comparison_period p on n.month_key between p.first_month_key and p.last_month_key
            group by p.period_key""").fetchall():
        national[key] = dict(zip(["scheduled", "on_time_arrival_rate",
                                  "on_time_departure_rate", "cancellation_rate"], vals))
    # The 12-month window ending in the latest month must equal the period sum.
    rolling_latest = con.sql("""select rolling_12m_on_time_arrival_rate from met_national_month
                                order by month_key desc limit 1""").fetchone()[0]
    assert abs(rolling_latest - national["latest_12m"]["on_time_arrival_rate"]) < 1e-12

    trough_month, trough_rate = con.sql("""
        select strftime(month_start, '%b %Y'), rolling_12m_on_time_arrival_rate
        from met_national_month where rolling_12m_on_time_arrival_rate is not null
        order by rolling_12m_on_time_arrival_rate limit 1""").fetchone()
    pre2020_low_month, pre2020_low = con.sql("""
        select strftime(month_start, '%b %Y'), rolling_12m_on_time_arrival_rate
        from met_national_month where rolling_12m_on_time_arrival_rate is not null
          and month_start < date '2020-01-01'
        order by rolling_12m_on_time_arrival_rate limit 1""").fetchone()
    peak_cancel_month, peak_cancel = con.sql("""
        select strftime(month_start, '%b %Y'), rolling_12m_cancellation_rate
        from met_national_month order by rolling_12m_cancellation_rate desc nulls last limit 1""").fetchone()
    fy_rows = con.sql("""
        select d.financial_year_label, sum(n.sectors_scheduled),
               sum(n.arrivals_on_time) / sum(n.sectors_flown),
               sum(n.cancellations) / sum(n.cancellation_base),
               count(*)
        from met_national_month n join dim_month d using (month_key)
        where d.financial_year >= 2019
        group by d.financial_year_label order by 1""").fetchall()
    chart_national(con, charts / "national_reliability.png", national["long_run_pre_covid"])

    national_table = md_table(
        ["Period", "Flights scheduled", "On-time arrivals", "On-time departures", "Cancellations"],
        [[f"{periods[k][0]}", f"{national[k]['scheduled']:,.0f}",
          pct(national[k]["on_time_arrival_rate"]), pct(national[k]["on_time_departure_rate"]),
          pct(national[k]["cancellation_rate"], 2)]
         for k in ("long_run_pre_covid", "pre_covid_fy19", "latest_12m")])
    fy_table = md_table(
        ["Financial year", "Flights scheduled", "On-time arrivals", "Cancellations", "Months"],
        [[fy, f"{s:,.0f}", pct(a), pct(c, 2), m] for fy, s, a, c, m in fy_rows])

    # Airlines (whole networks) ------------------------------------------
    brand_rows = con.sql("""
        select coalesce(l.brand_family, f.brand_family),
               f.on_time_arrival_rate, l.on_time_arrival_rate,
               f.cancellation_rate, l.cancellation_rate,
               f.sectors_scheduled, l.sectors_scheduled,
               l.share_of_national_scheduled,
               coalesce(f.is_ranked, false), coalesce(l.is_ranked, false)
        from (select * from met_brand_period where period_key = 'pre_covid_fy19') f
        full join (select * from met_brand_period where period_key = 'latest_12m') l
            using (brand_family)
        order by l.sectors_scheduled desc nulls last, f.sectors_scheduled desc""").fetchall()
    both = [r for r in brand_rows if r[8] and r[9]]
    chart_dumbbell(charts / "airlines_fy19_vs_latest.png",
                   [(r[0], r[1], r[2], r[3], r[4]) for r in both],
                   f"{sum(r[2] < r[1] for r in both)} of {len(both)} major airlines are less punctual "
                   "than in FY2018-19")
    brand_table = md_table(
        ["Brand family", "Flights, latest 12m", "Share", "On time FY19", "On time latest",
         "Change", "Cancelled FY19", "Cancelled latest"],
        [[r[0], "–" if r[6] is None else f"{r[6]:,.0f}", pct(r[7]), pct(r[1]), pct(r[2]),
          pts(r[2] - r[1]) if r[1] is not None and r[2] is not None else "–",
          pct(r[3], 2), pct(r[4], 2)]
         for r in brand_rows])
    n_brand_worse = sum(r[2] < r[1] for r in both)
    n_brand_fewer_cancel = sum(r[4] < r[3] for r in both)

    # Airlines on the same route ----------------------------------------
    top_pairs = [r[0] for r in con.sql(f"""
        select city_pair_name from met_city_pair_period where period_key = 'latest_12m'
        order by sectors_scheduled desc limit {TOP_CITY_PAIRS}""").fetchall()]
    same_route = con.sql(f"""
        select city_pair_name, brand_family, on_time_arrival_rate, cancellation_rate,
               sectors_scheduled, share_of_city_pair_scheduled, is_ranked
        from met_city_pair_brand_period
        where period_key = 'latest_12m'
          and city_pair_name in ({", ".join(f"'{p}'" for p in top_pairs)})
        order by city_pair_name, on_time_arrival_rate desc""").fetchall()
    ranked_same = [r for r in same_route if r[6]]
    unexpected = {r[1] for r in ranked_same} - set(BRAND_COLOR)
    assert not unexpected, f"no colour assigned for {unexpected}"
    chart_same_route(charts / "same_route_airlines.png", top_pairs,
                     [(r[0], r[1], r[2], r[3]) for r in ranked_same],
                     f"Same route, different airline: the {TOP_CITY_PAIRS} busiest city pairs")
    spreads = []
    for pair in top_pairs:
        rs = [r for r in ranked_same if r[0] == pair]
        best, worst = max(rs, key=lambda r: r[2]), min(rs, key=lambda r: r[2])
        spreads.append([pair, f"{best[1]} {pct(best[2])}", f"{worst[1]} {pct(worst[2])}",
                        f"{100 * (best[2] - worst[2]):.1f} pts"])
    gaps = [max(r[2] for r in ranked_same if r[0] == p) - min(r[2] for r in ranked_same if r[0] == p)
            for p in top_pairs]
    top_pair_rates = [r[1] for r in con.sql(f"""
        select city_pair_name, on_time_arrival_rate from met_city_pair_period
        where period_key = 'latest_12m'
          and city_pair_name in ({", ".join(f"'{p}'" for p in top_pairs)})""").fetchall()]
    route_spread = max(top_pair_rates) - min(top_pair_rates)
    spread_table = md_table(["City pair", "Most punctual", "Least punctual", "Gap"], spreads)
    same_route_table = md_table(
        ["City pair", "Brand family", "Flights", "Share of pair", "On time", "Cancelled", "Ranked"],
        [[r[0], r[1], f"{r[4]:,.0f}", pct(r[5]), pct(r[2]), pct(r[3], 2), "yes" if r[6] else "below floor"]
         for r in same_route])

    # Routes --------------------------------------------------------------
    listed_rate = scalar(con, """
        select sum(arrivals_on_time) / sum(sectors_flown) from met_city_pair_period
        where period_key = 'latest_12m'""")
    pairs = con.sql("""
        select city_pair_name, on_time_arrival_rate, cancellation_rate, sectors_scheduled,
               months_below_national, airlines
        from met_city_pair_period where period_key = 'latest_12m' and is_ranked
        order by on_time_arrival_rate, city_pair_name""").fetchall()
    n_pairs = scalar(con, "select count(*) from met_city_pair_period where period_key = 'latest_12m'")
    chart_city_pairs(charts / "city_pairs_latest.png", [(r[0], r[1]) for r in pairs], listed_rate,
                     f"On-time arrivals by city pair, {latest_label}")

    def pair_rows(rs):
        return [[r[0], f"{r[3]:,.0f}", pct(r[1]), pct(r[2], 2), f"{r[4]} of 12"] for r in rs]
    pair_headers = ["City pair", "Flights", "On time", "Cancelled", "Months below national"]
    worst_table = md_table(pair_headers, pair_rows(pairs[:5]))
    best_table = md_table(pair_headers, pair_rows(pairs[::-1][:5]))
    by_cancel = sorted(pairs, key=lambda r: (-r[2], r[0]))
    cancel_table = md_table(pair_headers, pair_rows(by_cancel[:5]))
    punctuality_rank = {r[0]: i + 1 for i, r in enumerate(pairs[::-1])}
    top_cancel = by_cancel[0]
    rho = spearman([r[1] for r in pairs], [r[2] for r in pairs])

    low = con.sql(f"""
        select city_pair_name, on_time_arrival_rate, sectors_scheduled
        from met_city_pair_period
        where period_key = 'latest_12m' and sectors_scheduled >= {LOW_FLOOR} * months_in_period
        order by on_time_arrival_rate, city_pair_name""").fetchall()
    ranked_names = {r[0] for r in pairs}
    low_new_worst = [r for r in low[:5] if r[0] not in ranked_names]
    low_new_best = [r for r in low[::-1][:5] if r[0] not in ranked_names]

    recovery = con.sql("""
        select l.city_pair_name, f.on_time_arrival_rate, l.on_time_arrival_rate,
               f.cancellation_rate, l.cancellation_rate
        from met_city_pair_period l
        join met_city_pair_period f using (city_pair_key)
        where l.period_key = 'latest_12m' and f.period_key = 'pre_covid_fy19'
          and l.is_ranked and f.is_ranked
        order by l.on_time_arrival_rate - f.on_time_arrival_rate, l.city_pair_name""").fetchall()
    n_rec = len(recovery)
    n_rec_worse = sum(r[2] < r[1] for r in recovery)
    recovery_table = md_table(
        ["City pair", "On time FY19", "On time latest", "Change", "Cancelled FY19", "Cancelled latest"],
        [[r[0], pct(r[1]), pct(r[2]), pts(r[2] - r[1]), pct(r[3], 2), pct(r[4], 2)]
         for r in recovery[:5] + recovery[-3:]])

    # Airports ------------------------------------------------------------
    ports = con.sql("""
        select l.port_name, l.state, l.sectors_scheduled, l.routes_listed,
               l.on_time_departure_rate, f.on_time_departure_rate, l.cancellation_rate
        from met_departing_port_period l
        left join met_departing_port_period f
            on f.port_key = l.port_key and f.period_key = 'pre_covid_fy19'
        where l.period_key = 'latest_12m' and l.is_ranked
        order by l.on_time_departure_rate, l.port_name""").fetchall()
    n_ports = scalar(con, "select count(*) from met_departing_port_period where period_key = 'latest_12m'")
    port_table = md_table(
        ["Departing port", "State", "Departures", "Routes", "On-time departures",
         "FY19", "Change", "Cancelled"],
        [[r[0], r[1], f"{r[2]:,.0f}", r[3], pct(r[4]), pct(r[5]),
          pts(r[4] - r[5]) if r[5] is not None else "–", pct(r[6], 2)] for r in ports])

    missing_rows, missing_from, missing_to = con.sql("""
        select count(*), min(month_key) // 100, max(month_key) // 100
        from fct_route_month where cancellations is null""").fetchone()
    lr, fy19, lt = (national[k] for k in ("long_run_pre_covid", "pre_covid_fy19", "latest_12m"))
    worst, best = pairs[0], pairs[-1]

    return f"""# Metrics and business answers

*Generated by `scripts/analyse.py` from the dbt metrics models in `data/warehouse.duckdb`.
Do not edit by hand.*

## Metric definitions

Defined once in [`warehouse/macros/otp_metrics.sql`](../warehouse/macros/otp_metrics.sql) and
used by every metrics model. Each rate is a **ratio of sums**: counts are added up first and
divided once, so a 30-flight route doesn't weigh as much as a 5,000-flight one.

| Metric | Formula (BITRE's definitions) | Notes |
|---|---|---|
| On-time arrival rate | arrivals on time ÷ sectors flown | on time = at the gate < 15 min after schedule |
| On-time departure rate | departures on time ÷ sectors flown | the headline for airports |
| Cancellation rate | cancellations ÷ sectors scheduled | rows with no cancellation count ({missing_rows}, {missing_from}–{missing_to}) leave both sides |

Periods: **{periods['long_run_pre_covid'][0]}** (long-run, pre-COVID), **{periods['pre_covid_fy19'][0]}**
(the last full year before COVID) and the **latest 12 months, {latest_label}**. League tables only
rank a route, airport or airline-on-route with {floor_note} scheduled flights a month on average
(about 10 a day; `ranking_min_flights_per_month` in `dbt_project.yml`).

## 1. National: has reliability recovered since COVID?

![National on-time arrivals and cancellations, rolling 12 months](charts/national_reliability.png)

{national_table}

- **Punctuality {"hasn't recovered" if lt['on_time_arrival_rate'] < fy19['on_time_arrival_rate'] else "has recovered"}.** {pct(lt['on_time_arrival_rate'])} of flights arrived on time in the latest
  12 months, vs {pct(fy19['on_time_arrival_rate'])} in FY2018-19 and {pct(lr['on_time_arrival_rate'])} on average over the 15 years before
  COVID ({pts(lt['on_time_arrival_rate'] - lr['on_time_arrival_rate'])}).
- **It has climbed back from a record low.** The 12 months to {trough_month} were the least punctual
  in the series at {pct(trough_rate)}; the worst 12 months before 2020 ended {pre2020_low_month}, at {pct(pre2020_low)}.
- **Cancellations.** {pct(lt['cancellation_rate'], 2)} in the latest 12 months:
  {word(lt['cancellation_rate'], fy19['cancellation_rate'])} FY2018-19's {pct(fy19['cancellation_rate'], 2)} and
  {word(lt['cancellation_rate'], lr['cancellation_rate'])} the long-run {pct(lr['cancellation_rate'], 2)}. They peaked at
  {pct(peak_cancel, 2)} in the 12 months to {peak_cancel_month} (COVID lockdowns and border closures).
- Volume is close to pre-COVID: {lt['scheduled']:,.0f} flights scheduled in the latest 12 months vs {fy19['scheduled']:,.0f} in
  FY2018-19 ({100 * (lt['scheduled'] / fy19['scheduled'] - 1):+.1f}%).

{fy_table}

The latest financial year is partial (months column).

## 2. Airlines: who runs on time?

![Airline on-time arrivals and cancellations, FY2018-19 vs latest 12 months](charts/airlines_fy19_vs_latest.png)

Whole networks, by brand family (Regional Express and Rex Airlines are one family). The chart
shows the brands above the volume floor in both periods.

{brand_table}

- **{n_brand_worse} of {len(both)}** major brands are less punctual than in FY2018-19, and **{n_brand_fewer_cancel} of {len(both)}** cancel
  a smaller share of flights. Brands above the floor in only one period are in the table, not the chart.
- Network-level comparisons mix in **where** an airline flies: QantasLink and Hinterland fly
  mostly regional routes, Jetstar is leisure-heavy. The fair comparison is on the same route.

## 3. Same route, different airline

![On-time arrivals by airline on the five busiest city pairs](charts/same_route_airlines.png)

On the {TOP_CITY_PAIRS} busiest city pairs ({latest_label}, both directions), the gap between the
most and least punctual airline on the same route is {100 * min(gaps):.1f} to {100 * max(gaps):.1f} points.
Between the five routes themselves (all airlines together) it is {100 * route_spread:.1f} points.
{"So the airline you book matters more than which of these routes you fly." if min(gaps) > route_spread else ""}

{spread_table}

{same_route_table}

Airlines under the floor (about 10 flights a day) are listed but not ranked or charted.

## 4. Routes: the worst and best

![On-time arrivals by city pair, latest 12 months](charts/city_pairs_latest.png)

{len(pairs)} of the {n_pairs} listed city pairs clear the volume floor. Across them, all airlines
together arrived on time on {pct(listed_rate)} of listed-route flights (national, all routes:
{pct(lt['on_time_arrival_rate'])}). "Months below national" counts the months a city pair ran under
that month's national rate: a check that a ranking isn't one bad month.

**Least punctual**

{worst_table}

**Most punctual**

{best_table}

**Most cancellations**

{cancel_table}

- Late and cancelled are different problems: the rank correlation between a city pair's
  on-time rate and its cancellation rate is **{rho:+.2f}**. {top_cancel[0]} cancels the most
  ({pct(top_cancel[2], 2)}) yet ranks {punctuality_rank[top_cancel[0]]} of {len(pairs)} for punctuality.
- **Floor sensitivity.** At a floor of {LOW_FLOOR} flights a month ({len(low)} city pairs), the least
  punctual five gain {", ".join(f"{r[0]} ({pct(r[1])}, {r[2]:,.0f} flights)" for r in low_new_worst) or "nothing new"};
  the most punctual five gain {", ".join(f"{r[0]} ({pct(r[1])}, {r[2]:,.0f} flights)" for r in low_new_best) or "nothing new"}.

**Recovery by route.** {n_rec_worse} of the {n_rec} city pairs ranked in both periods are less punctual
than in FY2018-19. Largest falls and largest gains:

{recovery_table}

## 5. Airports: on-time departures

Departing port, over the listed routes that leave it ({len(ports)} of {n_ports} ports clear the floor;
smaller ports are in `met_departing_port_period`).

{port_table}

The least punctual departure points are {ports[0][0]} ({pct(ports[0][4])}) and {ports[1][0]}
({pct(ports[1][4])}); the most punctual is {ports[-1][0]} ({pct(ports[-1][4])}). Least punctual city pair:
{worst[0]} ({pct(worst[1])}); most punctual: {best[0]} ({pct(best[1])}).
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    con = duckdb.connect(str(args.db), read_only=True)
    report = build(con, args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")


if __name__ == "__main__":
    main()
