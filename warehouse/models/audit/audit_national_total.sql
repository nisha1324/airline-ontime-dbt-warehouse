-- BITRE's published national row next to the warehouse's national total
-- (the sum of fct_network_month), one row per month. Not for reporting:
-- it documents the choice made in fct_network_month and shows its size.
-- `gap_airline` names the airline whose whole network equals the gap,
-- when exactly one does.

with published as (

    select
        (year(month_start) * 100 + month(month_start))::integer as month_key,
        sectors_scheduled,
        sectors_flown,
        arrivals_on_time
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'network_all_airlines'

),

warehouse as (

    select
        month_key,
        sum(sectors_scheduled)  as sectors_scheduled,
        sum(sectors_flown)      as sectors_flown,
        sum(arrivals_on_time)   as arrivals_on_time
    from {{ ref('fct_network_month') }}
    group by month_key

),

compared as (

    select
        month_key,
        published.sectors_scheduled                  as published_scheduled,
        warehouse.sectors_scheduled                  as warehouse_scheduled,
        round(warehouse.sectors_scheduled - published.sectors_scheduled, 6)
                                                     as scheduled_gap,
        published.arrivals_on_time / published.sectors_flown
                                                     as published_on_time_rate,
        warehouse.arrivals_on_time / warehouse.sectors_flown
                                                     as warehouse_on_time_rate
    from published
    full join warehouse using (month_key)

),

gap_airline as (

    select compared.month_key, any_value(airline.airline_name) as airline_name
    from compared
    join {{ ref('fct_network_month') }} as fct
        on fct.month_key = compared.month_key
        and round(fct.sectors_scheduled, 6) = compared.scheduled_gap
    join {{ ref('dim_airline') }} as airline using (airline_key)
    where compared.scheduled_gap != 0
    group by compared.month_key
    having count(*) = 1

)

select
    compared.*,
    scheduled_gap != 0                               as has_gap,
    gap_airline.airline_name                         as gap_airline
from compared
left join gap_airline using (month_key)
