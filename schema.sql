CREATE TABLE IF NOT EXISTS actors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    href TEXT
);

CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    title TEXT,
    href TEXT,
    UNIQUE(actor_id, code),
    FOREIGN KEY(actor_id) REFERENCES actors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS magnets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    magnet TEXT NOT NULL,
    tags TEXT,
    size TEXT,
    UNIQUE(work_id, magnet),
    FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_works_actor ON works(actor_id);
CREATE INDEX IF NOT EXISTS idx_magnets_work ON magnets(work_id);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    href TEXT,
    UNIQUE(scope, name)
);

CREATE TABLE IF NOT EXISTS collection_works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    title TEXT,
    href TEXT,
    UNIQUE(collection_id, code),
    FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collection_magnets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_work_id INTEGER NOT NULL,
    magnet TEXT NOT NULL,
    tags TEXT,
    size TEXT,
    UNIQUE(collection_work_id, magnet),
    FOREIGN KEY(collection_work_id) REFERENCES collection_works(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_collections_scope ON collections(scope);
CREATE INDEX IF NOT EXISTS idx_collection_works_collection ON collection_works(collection_id);
CREATE INDEX IF NOT EXISTS idx_collection_magnets_work ON collection_magnets(collection_work_id);
