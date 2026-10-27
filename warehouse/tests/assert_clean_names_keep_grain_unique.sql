-- Merging spelling variants (seed airline_names) must not create two rows for
-- the same airline, route and month.
select airline_name, route_name, month_start, count(*) as n_rows
from {{ ref('stg_bitre__otp_monthly') }}
where airline_name is not null
group by all
having count(*) > 1
