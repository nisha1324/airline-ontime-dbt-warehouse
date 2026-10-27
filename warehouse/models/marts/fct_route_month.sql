-- Grain: one airline on one directional route in one month (the source's
-- leaf rows). Every measure is additive across airlines, routes and months,
-- so "all airlines on a route" is a SUM over this table: the published
-- route totals are not loaded (they disagree with their own airline rows in
-- 11 route-months; see results/SOURCE_PROFILE.md).
--
-- Only the competitive routes BITRE lists are here, which carry about three
-- quarters of national flights. Airline and national totals come from
-- fct_network_month, never from summing this table.

with route_rows as (

    select * from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_airline'

)

select
    route_rows.otp_row_id                            as route_month_id,
    (year(route_rows.month_start) * 100 + month(route_rows.month_start))::integer
                                                     as month_key,
    airline.airline_key,
    route.route_key,
    route.departing_port_key,
    route.arriving_port_key,

    route_rows.sectors_scheduled,
    route_rows.sectors_flown,
    route_rows.cancellations,
    route_rows.departures_on_time,
    route_rows.departures_delayed,
    route_rows.arrivals_on_time,
    route_rows.arrivals_delayed,

    route_rows.is_cancellations_missing,
    route_rows.has_fractional_counts,
    route_rows.is_schedule_balanced,
    route_rows.is_departures_balanced,
    route_rows.is_arrivals_balanced

from route_rows
left join {{ ref('dim_airline') }} as airline
    on route_rows.airline_name = airline.airline_name
left join {{ ref('dim_route') }} as route
    on route_rows.route_name = route.route_name
