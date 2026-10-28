-- Airline reliability by brand family and comparison period, from the
-- airlines' whole networks. Brand family follows an airline through a
-- rename (Regional Express -> Rex Airlines), so Rex's FY2018-19 baseline
-- is comparable with today.
--
-- Caveat for readers: brands fly different networks (QantasLink and
-- Hinterland are regional, Jetstar is low-cost leisure-heavy), so a gap
-- between two brands is partly where they fly, not only how well.
-- met_city_pair_brand_period compares airlines on the same route.

with network as (

    select
        period.period_key,
        airline.brand_family,
        airline.airline_name,
        fct.*
    from {{ ref('fct_network_month') }} as fct
    join {{ ref('dim_airline') }} as airline using (airline_key)
    join {{ ref('dim_comparison_period') }} as period
        on fct.month_key between period.first_month_key and period.last_month_key

),

summed as (

    select
        period_key,
        brand_family,
        {{ otp_components() }},
        count(distinct month_key)                    as months_reported,
        string_agg(distinct airline_name, '; ' order by airline_name)
                                                     as airlines
    from network
    group by period_key, brand_family

)

select
    summed.period_key,
    summed.brand_family,
    summed.airlines,
    summed.months_reported,
    period.months_in_period,
    summed.sectors_scheduled,
    summed.sectors_flown,
    summed.arrivals_on_time,
    summed.departures_on_time,
    summed.cancellations,
    summed.cancellation_base,
    summed.rows_missing_cancellations,
    {{ otp_rates() }},
    summed.sectors_scheduled
        / sum(summed.sectors_scheduled) over (partition by summed.period_key)
                                                     as share_of_national_scheduled,
    {{ is_ranked('summed.sectors_scheduled', 'period.months_in_period') }}
                                                     as is_ranked
from summed
join {{ ref('dim_comparison_period') }} as period using (period_key)
