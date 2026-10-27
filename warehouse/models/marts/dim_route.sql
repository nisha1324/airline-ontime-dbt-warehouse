-- One row per directional route (Sydney-Melbourne and Melbourne-Sydney are
-- two routes; BITRE reports each direction). city_pair groups the two
-- directions for reports that don't care which way the flight went.

with route_rows as (

    select departing_port, arriving_port, route_name, month_start
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_airline'

),

routes as (

    select
        route_name,
        departing_port,
        arriving_port,
        min(month_start)              as first_month_listed,
        max(month_start)              as last_month_listed,
        count(distinct month_start)   as months_listed
    from route_rows
    group by all

),

ports as (

    select * from {{ ref('ports') }}

)

select
    dep.iata_code || '-' || arr.iata_code            as route_key,
    routes.route_name,
    dep.iata_code                                    as departing_port_key,
    arr.iata_code                                    as arriving_port_key,
    routes.departing_port,
    routes.arriving_port,

    -- The pair is ordered by port name, so both directions share one value.
    case when routes.departing_port < routes.arriving_port
        then dep.iata_code || '-' || arr.iata_code
        else arr.iata_code || '-' || dep.iata_code
    end                                              as city_pair_key,
    least(routes.departing_port, routes.arriving_port) || ' - '
        || greatest(routes.departing_port, routes.arriving_port)
                                                     as city_pair_name,

    dep.state = arr.state                            as is_intrastate,
    dep.is_capital_city and arr.is_capital_city      as is_capital_to_capital,

    routes.first_month_listed,
    routes.last_month_listed,
    routes.months_listed

from routes
-- left joins: a port missing from the seed gives a null key, which the
-- not_null tests catch, instead of silently dropping the route
left join ports as dep on routes.departing_port = dep.port_name
left join ports as arr on routes.arriving_port = arr.port_name
