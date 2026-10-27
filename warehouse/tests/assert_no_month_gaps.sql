-- The national total must exist for every month from the first to the last,
-- or month-on-month comparisons in a report silently skip a month.
with months as (
    select month_start
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'network_all_airlines'
),
expected as (
    select unnest(generate_series(min(month_start), max(month_start), interval 1 month))::date
        as month_start
    from months
)
select expected.month_start
from expected
left join months using (month_start)
where months.month_start is null
