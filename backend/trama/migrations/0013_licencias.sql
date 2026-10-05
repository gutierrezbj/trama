-- Licencia por pack: licensed (comprado con licencia, se puede entregar a clientes),
-- reference (solo referencia: para aprender y decidir; lo de cliente se licencia aparte) o
-- unknown. Cada recurso hereda la de sus packs; con que uno tenga licencia, cuenta como licensed.
ALTER TABLE packs ADD COLUMN license TEXT NOT NULL DEFAULT 'unknown';
