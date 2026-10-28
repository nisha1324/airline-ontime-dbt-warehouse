-- Airport view: one row per departing port and comparison period, over the
-- listed routes that leave it. The on-time departure rate is the headline
-- here (it reflects the airport's turnarounds, gates and morning
-- congestion); on-time arrival describes the destination as much as the
-- origin. Listed routes only, so a port's figures cover its busy
-- competitive routes, not every flight.

with route_rows as (

    select
        period.period_key,
        period.months_in_period,
        port.port_key,
        port.port_name,
        port.state,
        port.is_capital_city,
        fct.*
    from {{ ref('fct_route_month') }} as fct
    join {{ ref('dim_port') }} as port on fct.departing_port_key = port.port_key
    join {{ ref('dim_comparison_period') }} as period
        on fct.month_key between period.first_month_key and period.last_month_key

),

summed as (

    select
        period_key,
        months_in_period,
        port_key,
        port_name,
        state,
        is_capital_city,
        {{ otp_components() }},
        count(distinct route_key)                    as routes_listed,
        count(distinct airline_key)                  as airlines
    from route_rows
    group by all

)

select
    period_key,
    port_key,
    port_name,
    state,
    is_capital_city,
    routes_listed,
    airlines,
    months_in_period,
    sectors_scheduled,
    sectors_flown,
    arrivals_on_time,
    departures_on_time,
    cancellations,
    cancellation_base,
    rows_missing_cancellations,
    {{ otp_rates() }},
    {{ is_ranked('sectors_scheduled', 'months_in_period') }}
                                                     as is_ranked
from summed
