CREATE TABLE preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locale TEXT NOT NULL CHECK (locale IN ('en-US', 'pl-PL')),
    theme TEXT NOT NULL CHECK (theme IN ('system', 'light', 'dark')),
    mode TEXT NOT NULL CHECK (mode IN ('simple', 'advanced'))
);
INSERT INTO preferences (id, locale, theme, mode)
VALUES (1, 'en-US', 'system', 'simple');
