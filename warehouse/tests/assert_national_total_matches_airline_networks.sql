{{ config(severity = 'warn') }}
-- The national ("All Airlines", "All Ports") row should equal the sum of the
-- airline network rows for the month. In a few months a newly reporting
-- airline's network is missing from the national total (see
-- results/SOURCE_PROFILE.md), so this warns rather than fails.
with airline_networks as (
    select month_start, sum(sectors_scheduled) as sectors_scheduled
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'network_airline'
    group by all
),
national as (
    select month_start, sectors_scheduled
    from {{ ref('stg_bitre__otp_monthly') }}
    where row_grain = 'network_all_airlines'
)
select
    month_start,
    national.sectors_scheduled          as national_scheduled,
    airline_networks.sectors_scheduled  as airline_networks_scheduled
from national
full join airline_networks using (month_start)
where round(national.sectors_scheduled, 6) is distinct from round(airline_networks.sectors_scheduled, 6)
