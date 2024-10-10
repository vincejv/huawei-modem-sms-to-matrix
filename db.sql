CREATE TABLE last_message (
    id SERIAL PRIMARY KEY,
    date TIMESTAMP
);
INSERT INTO last_message (id, date) VALUES (1, '1970-01-01 00:00:00');
INSERT INTO last_message (id, date) VALUES (2, '1970-01-01 00:00:00');
ALTER TABLE last_message ADD COLUMN index INTEGER DEFAULT -1;