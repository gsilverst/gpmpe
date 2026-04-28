CREATE TABLE IF NOT EXISTS generated_artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id INTEGER NOT NULL,
  artifact_type TEXT NOT NULL DEFAULT 'flyer' CHECK (artifact_type IN ('flyer', 'poster')),
  file_path TEXT NOT NULL,
  checksum TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('pending', 'complete', 'failed')),
  template_snapshot_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_artifacts_campaign
  ON generated_artifacts (campaign_id, created_at DESC);

INSERT OR REPLACE INTO app_meta (key, value)
VALUES ('schema_version', '004');
