{% test unique_combination(model, columns) %}
-- Fails on each combination of the columns that appears more than once:
-- the declared grain of a fact table.
select {{ columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
