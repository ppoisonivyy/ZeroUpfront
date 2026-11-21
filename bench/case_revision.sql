CREATE TABLE cases (
    id text PRIMARY KEY,
    member text NOT NULL,
    head integer NOT NULL DEFAULT 0
);
CREATE SEQUENCE finish_order;
CREATE TABLE revisions (
    case_id text REFERENCES cases,
    rev integer NOT NULL,
    plan text NOT NULL,
    estimate text NOT NULL,
    state text NOT NULL DEFAULT 'queued',
    attempt integer NOT NULL DEFAULT 0,
    result jsonb,
    finished bigint,
    PRIMARY KEY (case_id, rev)
);
CREATE TABLE uploads (
    case_id text NOT NULL,
    request_id text NOT NULL,
    base integer NOT NULL,
    plan text NOT NULL,
    estimate text NOT NULL,
    rev integer NOT NULL,
    PRIMARY KEY (case_id, request_id),
    FOREIGN KEY (case_id, rev) REFERENCES revisions
);
CREATE TABLE extractions (
    case_id text REFERENCES cases,
    digest text NOT NULL,
    reader text NOT NULL,
    page jsonb NOT NULL,
    PRIMARY KEY (case_id, digest, reader)
);
