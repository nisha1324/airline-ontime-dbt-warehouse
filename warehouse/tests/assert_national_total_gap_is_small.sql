-- The warehouse's national total (sum of airline networks) differs from
-- BITRE's published national row in a few months, by up to 2.4% of flights
-- (a newly reporting airline left out; see audit_national_total). Fail if a
-- future release opens a gap over 3%, or moves the on-time rate by more
-- than half a percentage point: the decision in fct_network_month would
-- then need revisiting, not silently carrying on.
select *
from {{ ref('audit_national_total') }}
where abs(scheduled_gap) / published_scheduled > 0.03
   or abs(warehouse_on_time_rate - published_on_time_rate) > 0.005
