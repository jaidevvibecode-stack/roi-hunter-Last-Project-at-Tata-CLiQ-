{#
  Cross-warehouse helpers. Production target = Redshift; CI / local tests run the SAME models on Postgres.
  Anything warehouse-specific lives here and nowhere else.
#}

{# Text value of key `key` inside a JSON/SUPER column holding a flat object. #}
{% macro json_text(col, key) -%}
  {{ return(adapter.dispatch('json_text', 'roi_hunter')(col, key)) }}
{%- endmacro %}

{% macro default__json_text(col, key) -%}
  json_extract_path_text({{ col }}::varchar, '{{ key }}')
{%- endmacro %}

{% macro postgres__json_text(col, key) -%}
  (({{ col }})::jsonb ->> '{{ key }}')
{%- endmacro %}

{# Value of the first element whose action_type = `action_type` in a Meta `actions` / `action_values` array. #}
{% macro action_value(col, action_type) -%}
  {{ return(adapter.dispatch('action_value', 'roi_hunter')(col, action_type)) }}
{%- endmacro %}

{# Redshift: raw column is JSON text -> json_parse -> SUPER. UNVERIFIED against a live cluster — confirm in spike P0.3. #}
{% macro default__action_value(col, action_type) -%}
  json_extract_path_text(
    json_serialize(filter(json_parse({{ col }}), x -> x.action_type = '{{ action_type }}')),
    '[0]', 'value'
  )
{%- endmacro %}

{% macro postgres__action_value(col, action_type) -%}
  (select e->>'value' from jsonb_array_elements(coalesce(({{ col }})::jsonb, '[]'::jsonb)) e
    where e->>'action_type' = '{{ action_type }}' limit 1)
{%- endmacro %}

{# Render a list var as a SQL IN-list of string literals. #}
{% macro sql_list(values) -%}
  ({% for v in values %}'{{ v }}'{% if not loop.last %}, {% endif %}{% endfor %})
{%- endmacro %}
