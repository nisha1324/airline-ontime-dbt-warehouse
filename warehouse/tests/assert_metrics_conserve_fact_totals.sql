-- Every metrics table must add back to the facts it came from, in every
-- comparison period: no flight dropped by a join, none counted twice.
--   network side: national months and brand families = fct_network_month
--   route side:   city pairs, airlines on city pairs and departing ports
--                 = fct_route_month
-- One row per period and table that disagrees on any summed count.

{% set measures = ['sectors_scheduled', 'sectors_flown', 'arrivals_on_time',
                   'departures_on_time', 'cancellations', 'cancellation_base'] %}

with periods as (

    select * from {{ ref('dim_comparison_period') }}

),

network_fact as (

    select p.period_key,
        {% for m in measures %}
        {% if m == 'cancellation_base' %}
        sum(f.sectors_scheduled) filter (where f.cancellations is not null) as {{ m }}
        {% else %}
        sum(f.{{ m }}) as {{ m }}
        {% endif %}{{ ',' if not loop.last }}
        {% endfor %}
    from {{ ref('fct_network_month') }} f
    join periods p on f.month_key between p.first_month_key and p.last_month_key
    group by p.period_key

),

route_fact as (

    select p.period_key,
        {% for m in measures %}
        {% if m == 'cancellation_base' %}
        sum(f.sectors_scheduled) filter (where f.cancellations is not null) as {{ m }}
        {% else %}
        sum(f.{{ m }}) as {{ m }}
        {% endif %}{{ ',' if not loop.last }}
        {% endfor %}
    from {{ ref('fct_route_month') }} f
    join periods p on f.month_key between p.first_month_key and p.last_month_key
    group by p.period_key

),

metrics as (

    select 'met_national_month' as tbl, 'network' as side, p.period_key,
        {% for m in measures %}sum(n.{{ m }}) as {{ m }}{{ ',' if not loop.last }}{% endfor %}
    from {{ ref('met_national_month') }} n
    join periods p on n.month_key between p.first_month_key and p.last_month_key
    group by p.period_key

    union all

    select 'met_brand_period', 'network', period_key,
        {% for m in measures %}sum({{ m }}){{ ',' if not loop.last }}{% endfor %}
    from {{ ref('met_brand_period') }} group by period_key

    union all

    select 'met_city_pair_period', 'route', period_key,
        {% for m in measures %}sum({{ m }}){{ ',' if not loop.last }}{% endfor %}
    from {{ ref('met_city_pair_period') }} group by period_key

    union all

    select 'met_city_pair_brand_period', 'route', period_key,
        {% for m in measures %}sum({{ m }}){{ ',' if not loop.last }}{% endfor %}
    from {{ ref('met_city_pair_brand_period') }} group by period_key

    union all

    select 'met_departing_port_period', 'route', period_key,
        {% for m in measures %}sum({{ m }}){{ ',' if not loop.last }}{% endfor %}
    from {{ ref('met_departing_port_period') }} group by period_key

),

expected as (

    select 'network' as side, * from network_fact
    union all
    select 'route', * from route_fact

),

tables as (

    select * from (values
        ('met_national_month', 'network'),
        ('met_brand_period', 'network'),
        ('met_city_pair_period', 'route'),
        ('met_city_pair_brand_period', 'route'),
        ('met_departing_port_period', 'route')
    ) as t(tbl, side)

)

select tables.tbl, expected.period_key
from tables
join expected using (side)
left join metrics using (tbl, side, period_key)
where metrics.tbl is null
{% for m in measures %}
   or round(metrics.{{ m }}, 6) is distinct from round(expected.{{ m }}, 6)
{% endfor %}
