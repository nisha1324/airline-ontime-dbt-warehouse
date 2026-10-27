-- A city pair is the two directions of one route: a route and its reverse
-- must share city_pair_key, and no other route may use it.
with pairs as (
    select city_pair_key, count(*) as n_routes, count(distinct departing_port_key) as n_origins
    from {{ ref('dim_route') }}
    group by city_pair_key
)
select 'too many routes' as problem, city_pair_key, null as route_key
from pairs
where n_routes > 2 or n_origins != n_routes

union all

select 'reverse has another pair', route.city_pair_key, route.route_key
from {{ ref('dim_route') }} as route
join {{ ref('dim_route') }} as reverse
    on route.departing_port_key = reverse.arriving_port_key
    and route.arriving_port_key = reverse.departing_port_key
where route.city_pair_key != reverse.city_pair_key
