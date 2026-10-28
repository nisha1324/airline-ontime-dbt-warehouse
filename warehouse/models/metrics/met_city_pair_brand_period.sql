-- Airlines compared on the same route: one row per city pair, brand
-- family and comparison period. This is the fair airline comparison
-- (same airports, same weather, same congestion); met_brand_period mixes
-- in where each airline flies.

with route_rows as (

    select
        period.period_key,
        period.months_in_period,
        route.city_pair_key,
        route.city_pair_name,
        airline.brand_family,
        fct.*
    from {{ ref('fct_route_month') }} as fct
    join {{ ref('dim_route') }} as route using (route_key)
    join {{ ref('dim_airline') }} as airline using (airline_key)
    join {{ ref('dim_comparison_period') }} as period
        on fct.month_key between period.first_month_key and period.last_month_key

),

summed as (

    select
        period_key,
        months_in_period,
        city_pair_key,
        city_pair_name,
        brand_family,
        {{ otp_components() }},
        count(distinct month_key)                    as months_listed
    from route_rows
    group by all

)

select
    period_key,
    city_pair_key,
    city_pair_name,
    brand_family,
    months_listed,
    months_in_period,
    sectors_scheduled,
    sectors_flown,
    arrivals_on_time,
    departures_on_time,
    cancellations,
    cancellation_base,
    rows_missing_cancellations,
    {{ otp_rates() }},
    sectors_scheduled
        / sum(sectors_scheduled) over (partition by period_key, city_pair_key)
                                                     as share_of_city_pair_scheduled,
    {{ is_ranked('sectors_scheduled', 'months_in_period') }}
                                                     as is_ranked
from summed
