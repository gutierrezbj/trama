-- 0001: esquema inicial de TRAMA (E1)
CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'local',
  label TEXT NOT NULL,
  root_path TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE asset_versions (
  id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  size INTEGER NOT NULL,
  ext TEXT NOT NULL,
  media_kind TEXT NOT NULL,             -- video | audio | image | other
  analysis_status TEXT NOT NULL DEFAULT 'pending', -- pending | running | done | failed
  analysis_error TEXT,
  analysis TEXT,                        -- JSON con datos medidos (ffprobe / Pillow)
  analyzed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE assets (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES asset_versions(id),
  original_title TEXT NOT NULL,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'otros',
  category_source TEXT NOT NULL DEFAULT 'inferred',   -- inferred | human
  description TEXT NOT NULL DEFAULT '',
  description_source TEXT NOT NULL DEFAULT 'none',    -- none | human | inferred
  tags TEXT NOT NULL DEFAULT '[]',                    -- JSON array
  favorite INTEGER NOT NULL DEFAULT 0,
  search_text TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_assets_version ON assets(version_id);
CREATE INDEX idx_assets_category ON assets(category);
CREATE INDEX idx_assets_favorite ON assets(favorite);

CREATE TABLE locations (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES asset_versions(id),
  source_id TEXT NOT NULL REFERENCES sources(id),
  rel_path TEXT NOT NULL,
  file_name TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'available',   -- available | offline
  last_seen_at TEXT NOT NULL,
  UNIQUE(source_id, rel_path)
);
CREATE INDEX idx_locations_version ON locations(version_id);

CREATE TABLE derivatives (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES asset_versions(id),
  kind TEXT NOT NULL,      -- thumb | proxy | proxy_dark | proxy_light | proxy_checker | waveform | audio_proxy
  recipe TEXT NOT NULL,    -- versión de la receta
  rel_path TEXT,
  mime TEXT,
  width INTEGER,
  height INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | failed | unsupported
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(version_id, kind)
);

CREATE TABLE imports (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  sub_path TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed | cancelled
  total_files INTEGER NOT NULL DEFAULT 0,
  processed INTEGER NOT NULL DEFAULT 0,
  added INTEGER NOT NULL DEFAULT 0,
  updated INTEGER NOT NULL DEFAULT 0,
  unchanged INTEGER NOT NULL DEFAULT 0,
  offline INTEGER NOT NULL DEFAULT 0,
  errors TEXT NOT NULL DEFAULT '[]',
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,          -- import | analyze | derive
  version_id TEXT REFERENCES asset_versions(id),
  import_id TEXT REFERENCES imports(id),
  status TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed | cancelled
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  progress REAL NOT NULL DEFAULT 0,
  message TEXT,
  error TEXT,
  payload TEXT NOT NULL DEFAULT '{}',
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX idx_jobs_status ON jobs(status, created_at);
CREATE INDEX idx_jobs_version ON jobs(version_id);

CREATE TABLE collections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE collection_assets (
  collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  added_at TEXT NOT NULL,
  PRIMARY KEY (collection_id, asset_id)
);

CREATE TABLE selections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE selection_items (
  selection_id TEXT NOT NULL REFERENCES selections(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  added_at TEXT NOT NULL,
  PRIMARY KEY (selection_id, asset_id)
);
