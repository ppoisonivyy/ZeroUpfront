#!/usr/bin/env bash
# Exercise a disposable local PostgreSQL queue. Never connect to an existing DB.
set -euo pipefail
scratch=$(mktemp -d /tmp/zeroupfront-pg.XXXXXXXX)
cleanup() {
  if [[ -f "$scratch/db/postmaster.pid" ]]; then
    pg_ctl -D "$scratch/db" -m fast -w stop >/dev/null
  fi
  rm -rf -- "$scratch"
}
trap cleanup EXIT
initdb -A trust --no-locale -U fixture -D "$scratch/db" >/dev/null
pg_ctl -D "$scratch/db" -l "$scratch/server.log" -o "-k $scratch -c listen_addresses=''" -w start >/dev/null
conn=(-h "$scratch" -p 5432 -U fixture)
sql=(psql -X -q -v ON_ERROR_STOP=1 "${conn[@]}" -d postgres)
"${sql[@]}" <<'SQL'
CREATE TABLE jobs (id bigint PRIMARY KEY, state text NOT NULL);
CREATE INDEX pending_jobs ON jobs (id) WHERE state='queued';
CREATE TABLE results (job_id bigint PRIMARY KEY REFERENCES jobs(id), result text NOT NULL);
SQL
cat > "$scratch/work.sql" <<'SQL'
BEGIN;
WITH picked AS (
    SELECT id FROM jobs WHERE state='queued' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE jobs SET state='running' FROM picked WHERE jobs.id=picked.id RETURNING jobs.id AS job_id
\gset
COMMIT;
BEGIN;
INSERT INTO results VALUES (:job_id, 'ready_for_review');
UPDATE jobs SET state='done' WHERE id=:job_id AND state='running';
COMMIT;
SQL
for clients in 1 4; do
  "${sql[@]}" -c "TRUNCATE results,jobs; INSERT INTO jobs SELECT n,'queued' FROM generate_series(1,800) AS n;"
  pgbench -n -M prepared "${conn[@]}" -c "$clients" -j "$clients" -t "$((800 / clients))" -f "$scratch/work.sql" postgres
  verified=$("${sql[@]}" -Atc "SELECT count(*) FROM jobs JOIN results ON jobs.id=results.job_id WHERE jobs.state='done'")
  [[ "$verified" == "800" ]]
done
