-- PII guard: fails (returns rows) if any column in our analytics schemas looks like contact PII.
select table_schema, table_name, column_name
from information_schema.columns
where table_schema in ('stg', 'int', 'mart')
  and (lower(column_name) like '%email%'
    or lower(column_name) like '%phone%'
    or lower(column_name) like '%mobile%'
    or lower(column_name) in ('distinct_id', 'first_name', 'last_name', 'address', 'pincode'))
