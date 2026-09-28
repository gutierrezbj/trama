-- Nivel 2 aplicado a la biblioteca: etiquetas de la IA de visión aparte de las de carpeta y de
-- las humanas, y qué modelo las puso. La descripción de la IA va en `description` con
-- description_source = 'inferred' solo si no había una escrita a mano.
ALTER TABLE assets ADD COLUMN ai_tags TEXT NOT NULL DEFAULT '[]';
ALTER TABLE assets ADD COLUMN ai_model TEXT;
