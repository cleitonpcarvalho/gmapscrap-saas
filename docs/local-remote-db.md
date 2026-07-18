# Legacy: local scraper with VPS database

The main database is now Supabase. Use the regular `docker-compose.yml` with the Supabase `DB_*` variables from `.env` for both local development and production.

Keep this guide only as a rollback/reference path for the old VPS-hosted PostgreSQL setup.

Use this when the Google Maps scraper should run on the local machine, but the leads must be saved in the production PostgreSQL database on the VPS.

## 1. Start the database bridge on the VPS

Run this on the VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/cleitonpcarvalho/gmapscrap-saas/main/scripts/vps-db-bridge.sh -o /tmp/vps-db-bridge.sh
chmod +x /tmp/vps-db-bridge.sh
/tmp/vps-db-bridge.sh up
```

This creates a small `socat` container attached to `gmapscrap_internal` and binds the bridge only to `127.0.0.1:15432` on the VPS.

Check it with:

```bash
/tmp/vps-db-bridge.sh status
```

Stop it with:

```bash
/tmp/vps-db-bridge.sh down
```

## 2. Open the SSH tunnel on the local machine

Run this from the project folder and keep the terminal open:

```bash
scripts/open-vps-db-tunnel.sh
```

The local port `5433` will point to the production PostgreSQL database through SSH.

## 3. Configure local environment

Create a local env file:

```bash
cp env.local-remote-db.example .env.local-remote-db
```

Fill `POSTGRES_PASSWORD` with the VPS PostgreSQL password. This file is ignored by Git.

## 4. Run the local app against the VPS database

In another terminal:

```bash
docker compose --env-file .env.local-remote-db -f docker-compose.local-remote-db.yml up --build
```

Open:

```text
http://localhost:3001
```

Any leads collected locally will be saved in the VPS database and will appear in production.
