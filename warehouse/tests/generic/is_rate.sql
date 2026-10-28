{% test is_rate(model, column_name) %}
-- Fails on rows where a rate is outside 0..1 (nulls are allowed: a rate
-- with a zero denominator is null, not zero).
select * from {{ model }} where {{ column_name }} < 0 or {{ column_name }} > 1
{% endtest %}
