-- Grain: one airline's whole domestic network in one month. This is the
-- table for airline and national figures.
--
-- The national total is the SUM over this table, not BITRE's published
-- "All Airlines" row. BITRE defines the industry total as all services of
-- the reporting airlines, and in 4 months the published row leaves out a
-- newly reporting airline (plus one unexplained gap in Mar 2006). Summing
-- the airline rows also means a report's grand total always equals the sum
-- of its airline bars. audit_national_total shows both side by side.

with network_rows as (

    select * from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'network_airline'

)

select
    network_rows.otp_row_id                          as network_month_id,
    (year(network_rows.month_start) * 100 + month(network_rows.month_start))::integer
                                                     as month_key,
    airline.airline_key,

    network_rows.sectors_scheduled,
    network_rows.sectors_flown,
    network_rows.cancellations,
    network_rows.departures_on_time,
    network_rows.departures_delayed,
    network_rows.arrivals_on_time,
    network_rows.arrivals_delayed,

    network_rows.has_fractional_counts,
    network_rows.is_schedule_balanced,
    network_rows.is_departures_balanced,
    network_rows.is_arrivals_balanced

from network_rows
left join {{ ref('dim_airline') }} as airline
    on network_rows.airline_name = airline.airline_name
