-- One row per source row: typed, airline names cleaned, and labelled with
-- its grain. The BITRE file stacks four grains in one table:
--
--   route_airline         one airline on one route        (the leaf rows)
--   route_all_airlines    all airlines on one route       (= sum of leaf rows)
--   network_airline       one airline's whole network     (> its listed routes)
--   network_all_airlines  every reporting airline         (the national total)
--
-- Summing a measure over the raw file mixes all four, so downstream models
-- must pick one grain. Nothing is dropped or corrected here; source defects
-- are flagged so marts can decide what to do with them.

with source as (

    select * from {{ source('bitre', 'otp_monthly') }}

),

airline_names as (

    select * from {{ ref('airline_names') }}

),

typed as (

    select
        trim(Route)                                  as route_name,
        trim(Departing_Port)                         as departing_port,
        trim(Arriving_Port)                          as arriving_port,
        trim(Airline)                                as airline_reported,
        make_date(cast(Year as integer), cast(Month_Num as integer), 1)
                                                     as month_start,
        Month                                        as month_label,

        -- Counts are read as double: 56 rows (2009 and 2011) carry
        -- fractional values such as 33233.45642, and casting to an integer
        -- would hide that.
        cast(Sectors_Scheduled as double)            as sectors_scheduled,
        cast(Sectors_Flown as double)                as sectors_flown,
        cast(Cancellations as double)                as cancellations,
        cast(Departures_On_Time as double)           as departures_on_time,
        cast(Arrivals_On_Time as double)             as arrivals_on_time,
        cast(Departures_Delayed as double)           as departures_delayed,
        cast(Arrivals_Delayed as double)             as arrivals_delayed

    from source

),

labelled as (

    select
        typed.*,

        case
            when departing_port = 'All Ports' and airline_reported = 'All Airlines'
                then 'network_all_airlines'
            when departing_port = 'All Ports' then 'network_airline'
            when airline_reported = 'All Airlines' then 'route_all_airlines'
            else 'route_airline'
        end                                          as row_grain,

        -- null on the "All Airlines" rows, which are not an airline
        airline_names.airline_name

    from typed
    left join airline_names
        on typed.airline_reported = airline_names.reported_name

)

select
    md5(route_name || '|' || airline_reported || '|' || cast(month_start as varchar))
                                                     as otp_row_id,
    route_name,
    departing_port,
    arriving_port,
    airline_reported,
    airline_name,
    month_start,
    month_label,
    row_grain,

    sectors_scheduled,
    sectors_flown,
    cancellations,
    departures_on_time,
    arrivals_on_time,
    departures_delayed,
    arrivals_delayed,

    -- Source-defect flags. A null cancellation count makes the schedule
    -- check unknowable, so it is null rather than false.
    cancellations is null                            as is_cancellations_missing,
    (
        sectors_scheduled  != floor(sectors_scheduled)
        or sectors_flown      != floor(sectors_flown)
        or cancellations      != floor(cancellations)
        or departures_on_time != floor(departures_on_time)
        or arrivals_on_time   != floor(arrivals_on_time)
        or departures_delayed != floor(departures_delayed)
        or arrivals_delayed   != floor(arrivals_delayed)
    ) is true                                        as has_fractional_counts,
    sectors_scheduled = sectors_flown + cancellations
                                                     as is_schedule_balanced,
    sectors_flown = departures_on_time + departures_delayed
                                                     as is_departures_balanced,
    sectors_flown = arrivals_on_time + arrivals_delayed
                                                     as is_arrivals_balanced

from labelled
