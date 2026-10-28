-- Route reliability: one row per city pair (both directions together) and
-- comparison period, from the listed competitive routes. Adds how often
-- the city pair ran below the national on-time arrival rate month by
-- month, a check that a ranking isn't one bad month, and the ranking flag
-- (volume floor in dbt_project.yml).

with route_rows as (

    select
        period.period_key,
        period.months_in_period,
        route.city_pair_key,
        route.city_pair_name,
        route.is_intrastate,
        route.is_capital_to_capital,
        fct.*
    from {{ ref('fct_route_month') }} as fct
    join {{ ref('dim_route') }} as route using (route_key)
    join {{ ref('dim_comparison_period') }} as period
        on fct.month_key between period.first_month_key and period.last_month_key

),

summed as (

    select
        period_key,
        months_in_period,
        city_pair_key,
        city_pair_name,
        is_intrastate,
        is_capital_to_capital,
        {{ otp_components() }},
        count(distinct airline_key)                  as airlines,
        count(distinct month_key)                    as months_listed
    from route_rows
    group by all

),

monthly as (

    select
        period_key,
        city_pair_key,
        month_key,
        sum(arrivals_on_time) / nullif(sum(sectors_flown), 0)
                                                     as on_time_arrival_rate
    from route_rows
    group by all

),

below_national as (

    select
        monthly.period_key,
        monthly.city_pair_key,
        count(*) filter (
            where monthly.on_time_arrival_rate < national.on_time_arrival_rate
        )                                            as months_below_national
    from monthly
    join {{ ref('met_national_month') }} as national using (month_key)
    group by all

)

select
    summed.period_key,
    summed.city_pair_key,
    summed.city_pair_name,
    summed.is_intrastate,
    summed.is_capital_to_capital,
    summed.airlines,
    summed.months_listed,
    summed.months_in_period,
    summed.sectors_scheduled,
    summed.sectors_flown,
    summed.arrivals_on_time,
    summed.departures_on_time,
    summed.cancellations,
    summed.cancellation_base,
    summed.rows_missing_cancellations,
    {{ otp_rates() }},
    below_national.months_below_national,
    {{ is_ranked('summed.sectors_scheduled', 'summed.months_in_period') }}
                                                     as is_ranked
from summed
left join below_national using (period_key, city_pair_key)
