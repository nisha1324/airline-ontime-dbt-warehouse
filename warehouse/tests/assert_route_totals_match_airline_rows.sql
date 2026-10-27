{{ config(severity = 'warn') }}
-- Each "All Airlines" route row should equal the sum of that route's airline
-- rows. A handful don't in the source (listed in results/SOURCE_PROFILE.md),
-- so this warns rather than fails; marts rebuild route totals from the
-- airline rows instead of trusting the published ones.
with airline_rows as (
    select route_name, month_start,
           sum(sectors_scheduled)  as sectors_scheduled,
           sum(sectors_flown)      as sectors_flown,
           sum(cancellations)      as cancellations,
           sum(arrivals_on_time)   as arrivals_on_time,
           sum(departures_on_time) as departures_on_time
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_airline'
    group by all
),
published as (
    select route_name, month_start, sectors_scheduled, sectors_flown,
           cancellations, arrivals_on_time, departures_on_time
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'route_all_airlines'
)
select
    route_name,
    month_start,
    published.sectors_scheduled  as published_scheduled,
    airline_rows.sectors_scheduled as airline_rows_scheduled
from published
full join airline_rows using (route_name, month_start)
where published.sectors_scheduled is distinct from airline_rows.sectors_scheduled
   or published.sectors_flown is distinct from airline_rows.sectors_flown
   or published.cancellations is distinct from airline_rows.cancellations
   or published.arrivals_on_time is distinct from airline_rows.arrivals_on_time
   or published.departures_on_time is distinct from airline_rows.departures_on_time
