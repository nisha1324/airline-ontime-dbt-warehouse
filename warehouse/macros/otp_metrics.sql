{#
  The metric definitions, written once and used by every metrics model.

  Every rate is a ratio of sums: add up the counts first, divide once. The
  average of monthly or per-route percentages would weight a 30-flight route
  the same as a 5,000-flight one. The models keep the summed counts next to
  the rates, so a BI tool can re-aggregate them the same way (Part 4's DAX
  measures divide the same sums).

  BITRE's definitions:
    on-time arrival rate   = arrivals on time   / sectors flown
    on-time departure rate = departures on time / sectors flown
    cancellation rate      = cancellations      / sectors scheduled

  Cancellations are missing on 316 route rows (Qantas Group, 2006-07). Those
  rows leave both the numerator and the denominator of the cancellation
  rate (`cancellation_base`), instead of counting as zero cancellations.
  They still count towards the on-time rates, which are complete.
#}

{% macro otp_components() %}
    sum(sectors_scheduled)                           as sectors_scheduled,
    sum(sectors_flown)                               as sectors_flown,
    sum(arrivals_on_time)                            as arrivals_on_time,
    sum(departures_on_time)                          as departures_on_time,
    sum(cancellations)                               as cancellations,
    coalesce(sum(sectors_scheduled) filter (where cancellations is not null), 0)
                                                     as cancellation_base,
    count(*) filter (where cancellations is null)    as rows_missing_cancellations
{% endmacro %}

{#
  Rates from the summed components. `prefix` reads and names a second set of
  components, e.g. rolling 12-month sums: prefix='rolling_12m_' divides
  rolling_12m_arrivals_on_time by rolling_12m_sectors_flown.
#}
{% macro otp_rates(prefix='') %}
    {{ prefix }}arrivals_on_time / nullif({{ prefix }}sectors_flown, 0)
                                                     as {{ prefix }}on_time_arrival_rate,
    {{ prefix }}departures_on_time / nullif({{ prefix }}sectors_flown, 0)
                                                     as {{ prefix }}on_time_departure_rate,
    {{ prefix }}cancellations / nullif({{ prefix }}cancellation_base, 0)
                                                     as {{ prefix }}cancellation_rate
{% endmacro %}

{#
  A route, airport or airline-on-route is ranked only if it averages at
  least `ranking_min_flights_per_month` scheduled flights over the period
  (dbt_project.yml), so a handful of bad days on a thin route can't top a
  league table.
#}
{% macro is_ranked(scheduled, months_in_period) %}
    {{ scheduled }} >= {{ var('ranking_min_flights_per_month') }} * {{ months_in_period }}
{% endmacro %}
