-- One row per airline (cleaned name). Renames are kept as separate rows,
-- because BITRE reported them separately; brand_family chains the ones that
-- are one continuing operation (see seed airline_brands for the evidence),
-- so a 20-year trend can follow Rex or Virgin Australia Regional Airlines
-- across a rename or merger.

with staged as (

    select * from {{ ref('stg_bitre__otp_monthly') }}
    where airline_name is not null

),

activity as (

    select
        airline_name,
        min(month_start) filter (where row_grain = 'network_airline')
                                                     as first_month_reported,
        max(month_start) filter (where row_grain = 'network_airline')
                                                     as last_month_reported,
        count(distinct month_start) filter (where row_grain = 'network_airline')
                                                     as months_reported,
        count(distinct route_name) filter (where row_grain = 'route_airline')
                                                     as routes_listed,
        string_agg(distinct airline_reported, '; ' order by airline_reported)
                                                     as reported_names
    from staged
    group by airline_name

),

latest as (

    select max(month_start) as latest_month from {{ ref('stg_bitre__otp_monthly') }}

)

select
    regexp_replace(lower(brands.airline_name), '[^a-z0-9]+', '_', 'g')
                                                     as airline_key,
    brands.airline_name,
    brands.brand_family,
    activity.reported_names,
    activity.first_month_reported,
    activity.last_month_reported,
    activity.months_reported,
    activity.routes_listed,
    -- Some smaller airlines report only a network total: no route detail.
    activity.routes_listed > 0                       as has_route_detail,
    activity.last_month_reported = latest.latest_month
                                                     as is_reporting_now,
    brands.lineage_note,
    brands.lineage_source
from {{ ref('airline_brands') }} as brands
left join activity using (airline_name)
cross join latest
