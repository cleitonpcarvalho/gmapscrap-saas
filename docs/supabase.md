# Supabase database

GmapScrap now uses Supabase Postgres as the primary database for local and production environments.

## Environment variables

Use the Supabase Session Pooler when running inside Docker or on an IPv4-only VPS:

```text
DB_HOST=aws-0-<region>.pooler.supabase.com
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres.<project-ref>
DB_PASSWORD=<supabase-database-password>
DB_SSLMODE=require
```

If the host has IPv6 support, the direct database host also works:

```text
DB_HOST=db.<project-ref>.supabase.co
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=<supabase-database-password>
DB_SSLMODE=require
```

Keep the Supabase API keys only in ignored local env files or deployment secrets:

```text
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SECRET_KEY=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=gmapscrap
```

## Local run

After filling `.env`, start only the backend and frontend:

```bash
docker compose up --build
```

The local compose file no longer starts PostgreSQL.

## Production run

Set the same `DB_*` and `SUPABASE_*` variables in Portainer/Swarm. The production compose no longer declares the `postgres` service or the old Postgres volume.

Before deleting the old VPS Postgres volume, compare counts between the old database and Supabase if there is any chance production has newer data than the local dump.
