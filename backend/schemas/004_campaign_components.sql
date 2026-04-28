CREATE TABLE IF NOT EXISTS campaign_components (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  component_key TEXT NOT NULL,
  component_kind TEXT NOT NULL DEFAULT 'featured-offers',
  display_title TEXT NOT NULL,
  subtitle TEXT,
  description_text TEXT,
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
  UNIQUE (campaign_id, component_key)
);

CREATE INDEX IF NOT EXISTS idx_campaign_components_campaign
  ON campaign_components (campaign_id, display_order, id);

CREATE TABLE IF NOT EXISTS campaign_component_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  component_id INTEGER NOT NULL,
  item_name TEXT NOT NULL,
  item_kind TEXT NOT NULL DEFAULT 'service',
  duration_label TEXT,
  item_value TEXT,
  description_text TEXT,
  terms_text TEXT,
  display_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (component_id) REFERENCES campaign_components(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_campaign_component_items_component
  ON campaign_component_items (component_id, display_order, id);

INSERT INTO app_meta (key, value)
VALUES ('schema_version', '004')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;