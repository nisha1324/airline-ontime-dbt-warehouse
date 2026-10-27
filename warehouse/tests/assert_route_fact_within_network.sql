-- Every airline-month in the route fact needs a network row (or the airline
-- would vanish from airline totals while showing on routes), and its listed
-- routes can't add up to more flights than its whole network.
with routes as (
    select airline_key, month_key, sum(sectors_scheduled) as route_sectors
    from {{ ref('fct_route_month') }}
    group by all
)
select routes.*, network.sectors_scheduled as network_sectors
from routes
left join {{ ref('fct_network_month') }} as network using (airline_key, month_key)
where network.sectors_scheduled is null
   or routes.route_sectors > network.sectors_scheduled
