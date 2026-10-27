{% test not_false(model, column_name) %}
-- Fails on rows where a boolean check is false. Null means "can't tell"
-- (e.g. the input was missing) and passes; count those separately.
select * from {{ model }} where {{ column_name }} = false
{% endtest %}
