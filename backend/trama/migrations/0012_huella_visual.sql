-- Huella visual de cada miniatura y parejas de «posibles versiones» del mismo recurso
-- (mismo efecto en otro formato, resolución o pack). No se fusiona nada automáticamente.
CREATE TABLE vprints (
  version_id TEXT PRIMARY KEY REFERENCES asset_versions(id),
  dhash TEXT,
  tiny BLOB,
  flat INTEGER NOT NULL DEFAULT 0,
  aspect REAL,
  duration REAL,
  media_kind TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE visual_twins (
  a TEXT NOT NULL,
  b TEXT NOT NULL,
  diff REAL NOT NULL,
  PRIMARY KEY (a, b)
);
CREATE INDEX idx_visual_twins_b ON visual_twins(b);
