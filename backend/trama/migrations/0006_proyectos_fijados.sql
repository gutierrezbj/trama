-- Proyectos fijados en la barra lateral (acceso directo bajo «Explorar»).
ALTER TABLE selections ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
