-- An airline's listed routes are a subset of its network, so their flights
-- can't add up to more than its network total for the month.
with routes as (
    select airline_name, month_start, sum(sectors_scheduled) as route_sectors
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_airline'
    group by all
),
network as (
    select airline_name, month_start, sectors_scheduled as network_sectors
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'network_airline'
)
select *
from routes
join network using (airline_name, month_start)
where route_sectors > network_sectors
