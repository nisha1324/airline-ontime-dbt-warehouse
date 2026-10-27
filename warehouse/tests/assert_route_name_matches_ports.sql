-- The Route column is derived from the two ports; if it ever disagrees,
-- dim_route can't be built from either one alone.
select *
from {{ ref('stg_bitre__otp_monthly') }}
where route_name != departing_port || '-' || arriving_port
   or (departing_port = arriving_port and departing_port != 'All Ports')
