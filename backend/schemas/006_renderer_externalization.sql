INSERT INTO app_meta (key, value)
VALUES ('schema_version', '006')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;
