-- One row per port on the published routes. Role-played in the facts as the
-- departing and the arriving port. "All Ports" is not a port (it marks a
-- network total) and has no row here.

with ports as (

    select * from {{ ref('ports') }}

),

route_ends as (

    select departing_port as port_name, month_start
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_airline'

    union all

    select arriving_port, month_start
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_airline'

),

activity as (

    select
        port_name,
        min(month_start) as first_month_listed,
        max(month_start) as last_month_listed
    from route_ends
    group by port_name

)

select
    ports.iata_code                                  as port_key,
    ports.port_name,
    ports.state,
    ports.is_capital_city,
    activity.first_month_listed,
    activity.last_month_listed
from ports
left join activity using (port_name)
