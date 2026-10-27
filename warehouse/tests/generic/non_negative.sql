{% test non_negative(model, column_name) %}
-- Fails on rows where the column is below zero (nulls are left to not_null).
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}
