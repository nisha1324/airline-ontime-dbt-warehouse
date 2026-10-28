-- National reliability, one row per month: the summed counts, the three
-- rates, and the same rates over the 12 months ending that month (ratio of
-- 12-month sums, so no seasonal swing and no averaging of percentages).
-- Built from fct_network_month, so the national total is the sum of the
-- airline networks (see audit_national_total).

with monthly as (

    select
        month_key,
        {{ otp_components() }},
        count(*)                                     as airlines_reporting
    from {{ ref('fct_network_month') }}
    group by month_key

),

rolling as (

    select
        monthly.*,
        month.month_start,
        sum(sectors_scheduled) over last_12      as rolling_12m_sectors_scheduled,
        sum(sectors_flown) over last_12          as rolling_12m_sectors_flown,
        sum(arrivals_on_time) over last_12       as rolling_12m_arrivals_on_time,
        sum(departures_on_time) over last_12     as rolling_12m_departures_on_time,
        sum(cancellations) over last_12          as rolling_12m_cancellations,
        sum(cancellation_base) over last_12      as rolling_12m_cancellation_base,
        min(month.month_start) over last_12      as rolling_12m_first_month,
        count(*) over last_12                    as rolling_12m_months
    from monthly
    join {{ ref('dim_month') }} as month using (month_key)
    -- 12 rows = 12 months: dim_month and the network rows have no gaps
    -- (assert_no_month_gaps), and assert_rolling_window_is_12_months
    -- checks the window's first month.
    window last_12 as (order by month_key rows between 11 preceding and current row)

),

with_rates as (

    select
        *,
        {{ otp_rates() }},
        {{ otp_rates(prefix='rolling_12m_') }}
    from rolling

)

select
    month_key,
    month_start,
    airlines_reporting,
    sectors_scheduled,
    sectors_flown,
    arrivals_on_time,
    departures_on_time,
    cancellations,
    cancellation_base,
    rows_missing_cancellations,
    on_time_arrival_rate,
    on_time_departure_rate,
    cancellation_rate,

    -- Rolling figures start once a full 12 months is available (Dec 2004).
    case when rolling_12m_months = 12 then rolling_12m_first_month end
                                                     as rolling_12m_first_month,
    case when rolling_12m_months = 12 then rolling_12m_sectors_scheduled end
                                                     as rolling_12m_sectors_scheduled,
    case when rolling_12m_months = 12 then rolling_12m_on_time_arrival_rate end
                                                     as rolling_12m_on_time_arrival_rate,
    case when rolling_12m_months = 12 then rolling_12m_on_time_departure_rate end
                                                     as rolling_12m_on_time_departure_rate,
    case when rolling_12m_months = 12 then rolling_12m_cancellation_rate end
                                                     as rolling_12m_cancellation_rate

from with_rates
