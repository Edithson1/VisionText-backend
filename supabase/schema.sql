-- Catalog accessed only through the backend. No public Data API policies.
CREATE TABLE IF NOT EXISTS public.images (
    id VARCHAR PRIMARY KEY,
    filename VARCHAR NOT NULL,
    description TEXT,
    image_path VARCHAR NOT NULL,
    thumbnail_path VARCHAR NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    size INTEGER NOT NULL,
    format VARCHAR NOT NULL,
    status VARCHAR DEFAULT 'completed',
    similarity_score FLOAT,
    created_at TIMESTAMP WITHOUT TIME ZONE,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    embedding BYTEA,
    embedding_model VARCHAR,
    storage_provider VARCHAR NOT NULL DEFAULT 's3'
);
ALTER TABLE public.images ADD COLUMN IF NOT EXISTS embedding BYTEA;
ALTER TABLE public.images ADD COLUMN IF NOT EXISTS embedding_model VARCHAR;
ALTER TABLE public.images ADD COLUMN IF NOT EXISTS storage_provider VARCHAR NOT NULL DEFAULT 's3';
CREATE INDEX IF NOT EXISTS images_created_at_idx ON public.images (created_at DESC);
ALTER TABLE public.images ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.images FROM anon, authenticated;
