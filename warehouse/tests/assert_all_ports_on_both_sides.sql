-- "All Ports" marks a network total, so it must be on both ends of the route
-- or neither. A row with only one side would be a third, undocumented grain.
select *
from {{ ref('stg_bitre__otp_monthly') }}
where (departing_port = 'All Ports') != (arriving_port = 'All Ports')
