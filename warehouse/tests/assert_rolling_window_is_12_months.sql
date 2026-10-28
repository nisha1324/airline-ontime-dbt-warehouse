-- The rolling 12-month rates use a 12-row window. That is 12 months only
-- if no month is missing; fail if any window starts anywhere other than
-- 11 months before the month it ends in.
select month_start, rolling_12m_first_month
from {{ ref('met_national_month') }}
where (rolling_12m_first_month is not null
       and rolling_12m_first_month != (month_start - interval 11 month)::date)
   or (rolling_12m_first_month is null
       and month_start >= (select min(month_start) + interval 11 month
                           from {{ ref('met_national_month') }}))
