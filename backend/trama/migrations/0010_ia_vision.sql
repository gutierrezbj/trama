-- Nivel 2: IA de visión. Una ejecución (prueba o pasada completa) guarda lo que dijo cada modelo
-- de cada recurso, con tokens, coste y tiempo medidos, y el voto del propietario en las pruebas.
CREATE TABLE ai_runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                 -- test | full
  models TEXT NOT NULL,               -- JSON: ["local:qwen/qwen3-vl-8b", "openai:gpt-6-luna", ...]
  sample TEXT NOT NULL DEFAULT '[]',   -- JSON: version_ids
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE ai_labels (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL REFERENCES asset_versions(id),
  model TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  seconds REAL NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, version_id, model)
);

CREATE TABLE ai_votes (
  run_id TEXT NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
  version_id TEXT NOT NULL,
  winner TEXT NOT NULL,               -- modelo ganador | tie | none
  voted_at TEXT NOT NULL,
  PRIMARY KEY (run_id, version_id)
);
