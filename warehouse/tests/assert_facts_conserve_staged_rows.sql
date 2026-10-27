-- Each fact must hold exactly the staged rows of its grain: the same number
-- of rows and the same totals for every measure, month by month. A key join
-- that fans out (a duplicated dimension row) or drops rows fails here.
with staged as (
    select
        case row_grain when 'route_airline' then 'fct_route_month'
                       else 'fct_network_month' end as fact,
        (year(month_start) * 100 + month(month_start))::integer as month_key,
        count(*)                                  as n_rows,
        round(sum(sectors_scheduled), 6)          as sectors_scheduled,
        round(sum(sectors_flown), 6)              as sectors_flown,
        round(sum(cancellations), 6)              as cancellations,
        round(sum(arrivals_on_time), 6)           as arrivals_on_time,
        round(sum(departures_on_time), 6)         as departures_on_time
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain in ('route_airline', 'network_airline')
    group by all
),
facts as (
    select 'fct_route_month' as fact, month_key, count(*) as n_rows,
           round(sum(sectors_scheduled), 6), round(sum(sectors_flown), 6),
           round(sum(cancellations), 6), round(sum(arrivals_on_time), 6),
           round(sum(departures_on_time), 6)
    from {{ ref('fct_route_month') }}
    group by all
    union all
    select 'fct_network_month', month_key, count(*),
           round(sum(sectors_scheduled), 6), round(sum(sectors_flown), 6),
           round(sum(cancellations), 6), round(sum(arrivals_on_time), 6),
           round(sum(departures_on_time), 6)
    from {{ ref('fct_network_month') }}
    group by all
)
(select 'staged only' as side, * from staged except select 'staged only', * from facts)
union all
(select 'fact only', * from facts except select 'fact only', * from staged)
