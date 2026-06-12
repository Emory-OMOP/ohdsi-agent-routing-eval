# Langfuse — observability stack

Langfuse is part of the full stack: the webapp and `omcp` send traces to it. This
directory self-hosts Langfuse v3 (web + worker + Postgres + ClickHouse + MinIO +
Redis) via Docker Compose, listening on **http://localhost:3000**.

## Bring it up

```bash
cd langfuse
cp env.example .env          # then edit .env (see comments there for secret generation)
docker compose up -d
# wait for health, then open http://localhost:3000
```

First run bootstraps an org, a project, and a login user from the `LANGFUSE_INIT_*`
values in `.env`.

## The two-key handshake (important)

There are **two** env files, and they must agree on the project keys:

| Where | File | Keys |
|---|---|---|
| Langfuse stack (here) | `langfuse/.env` | `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `LANGFUSE_INIT_PROJECT_SECRET_KEY` |
| App (webapp + servers) | repo-root `.env` | `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` |

Set the project public/secret keys here, then copy the **same** values into the
repo-root `.env` as `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` so the app's
traces land in this project. Langfuse key formats: public `pk-lf-…`, secret `sk-lf-…`.

## Running without Langfuse

Langfuse is optional for a quick stack test or if you already capture metadata
elsewhere. Skip this stack and set `LANGFUSE_ENABLED=false` in the repo-root `.env`
(and `ENABLE_LANGFUSE=false` for `omcp`). See the top-level `README.md`,
"Run without Langfuse."

## Ports

`3000` web · `3031` worker · `5433` Postgres · `8124`/`9001` ClickHouse ·
`9090`/`9091` MinIO · `6380` Redis (host-side; all but 3000 bound to localhost).

Stop: `docker compose down` · Wipe data: `docker compose down -v`.
