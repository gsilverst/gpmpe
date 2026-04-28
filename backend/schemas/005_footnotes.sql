INSERT INTO app_meta (key, value)
VALUES ('schema_version', '005')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;
