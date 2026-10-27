-- One row per month from the first to the last month in the source, with
-- calendar and Australian financial-year (July-June) attributes. month_key
-- is yyyymm as an integer: stable across rebuilds and cheap to join on.

with bounds as (

    select min(month_start) as first_month, max(month_start) as last_month
    from {{ ref('stg_bitre__otp_monthly') }}

),

months as (

    select unnest(generate_series(first_month, last_month, interval 1 month))::date
        as month_start
    from bounds

)

select
    (year(month_start) * 100 + month(month_start))::integer
                                                     as month_key,
    month_start,
    year(month_start)::integer                       as calendar_year,
    month(month_start)::integer                      as month_num,
    strftime(month_start, '%b')                      as month_name,
    strftime(month_start, '%b %Y')                   as month_label,
    quarter(month_start)::integer                    as calendar_quarter,

    -- Australian financial year: FY2025-26 runs Jul 2025 - Jun 2026.
    case when month(month_start) >= 7
        then year(month_start) + 1 else year(month_start)
    end::integer                                     as financial_year,
    case when month(month_start) >= 7
        then 'FY' || year(month_start) || '-' || right(cast(year(month_start) + 1 as varchar), 2)
        else 'FY' || (year(month_start) - 1) || '-' || right(cast(year(month_start) as varchar), 2)
    end                                              as financial_year_label,
    ((month(month_start) + 5) % 12 + 1)::integer     as financial_month_num,

    day(last_day(month_start))::integer              as days_in_month

from months
