-- The named windows the analysis compares. All are whole months; the
-- latest window moves forward when a new snapshot adds a month.
--
--   long_run_pre_covid  FY2004-05 to FY2018-19: 15 full financial years
--                       before COVID (Jan-Jun 2004 is left out so every
--                       year is complete).
--   pre_covid_fy19      FY2018-19, the last full year before COVID, the
--                       usual "back to normal?" baseline.
--   latest_12m          the 12 most recent months in the snapshot.

with latest as (

    select max(month_start) as last_month from {{ ref('dim_month') }}

),

periods as (

    select 1 as sort_order, 'long_run_pre_covid' as period_key,
           'FY2004-05 to FY2018-19' as period_label,
           date '2004-07-01' as first_month, date '2019-06-01' as last_month

    union all

    select 2, 'pre_covid_fy19', 'FY2018-19',
           date '2018-07-01', date '2019-06-01'

    union all

    select 3, 'latest_12m',
           strftime(last_month - interval 11 month, '%b %Y') || ' to '
               || strftime(last_month, '%b %Y'),
           (last_month - interval 11 month)::date, last_month
    from latest

)

select
    period_key,
    period_label,
    sort_order,
    (year(first_month) * 100 + month(first_month))::integer
                                                     as first_month_key,
    (year(last_month) * 100 + month(last_month))::integer
                                                     as last_month_key,
    first_month,
    last_month,
    (datediff('month', first_month, last_month) + 1)::integer
                                                     as months_in_period
from periods
