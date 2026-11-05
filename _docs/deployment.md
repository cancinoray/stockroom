# Deployment

Stockroom runs as one application container that serves both the API and the built React app,
plus a PostgreSQL 16 container. Both are described by the single `compose.yaml` in the repository
root. The same file runs on a developer machine and on the self-hosted Compose host; only the
image reference changes.

The release procedure — build once in CI, tag, pull, migrate, swap, smoke — lives in
[release-process.md](release-process.md). This document describes the running stack: what each
environment runs, how it starts, and how to check it.

## 1. The two environments

|                      | Local Compose                                   | Self-hosted Compose host                                                        |
| -------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------- |
| Application image    | `stockroom-app:local`, built from this checkout | `ghcr.io/cancinoray/stockroom:<tag>`, pulled from GHCR in the release procedure |
| Worked image example | `stockroom-app:local`                           | `ghcr.io/cancinoray/stockroom:20261105-180736-5271a4a`                          |
| Database             | the `db` service, `postgres:16`                 | the same `db` service                                                           |
| Host port            | `8000`, mapped to container port `8000`         | the same mapping; put the host's own proxy, DNS and TLS in front if needed      |
| Data                 | named volume `stockroom-db`                     | the same named volume                                                           |
| Environment          | the values declared in `compose.yaml`           | the same values, because it is the same file                                    |
| Start                | `docker compose up --build -d`                  | `STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<tag> docker compose up -d`       |

The single image variable is `STOCKROOM_IMAGE`. Its default is `stockroom-app:local`, so a local
build works with no environment variable. The host tag shape is stated once in
[release-process.md](release-process.md) §2; this document does not repeat it.

Do not invent a second spelling: the variable is `STOCKROOM_IMAGE`, the host reference is
`ghcr.io/cancinoray/stockroom:<tag>`, and the local reference is `stockroom-app:local`.

## 2. Start the local stack

```bash
docker compose up --build -d
```

Compose builds `stockroom-app:local` from the `Dockerfile`, starts `db`, waits for its
`pg_isready` healthcheck, then starts `app`. Because `compose.yaml` sets `name: stockroom`, the
Compose project is `stockroom`; the named volume is `stockroom_stockroom-db` and the containers
are `stockroom-app-1` and `stockroom-db-1`. Passing `-p` with a project name changes both the
project and the volume prefix.

Check that it is up:

```bash
curl -fsS http://localhost:8000/healthz
scripts/release-smoke.sh
```

`scripts/release-smoke.sh` defaults to `http://localhost:8000`; it accepts one optional base URL
when the stack is reached by another address. It runs the three checks described in §5 and exits
non-zero on any failure. Do not replace it with a hand-written `curl` sequence.

Stop the stack with `docker compose down`, which keeps the named volume, or
`docker compose down -v`, which deletes it.

## 3. Run a released image on the host

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:20261105-180736-5271a4a docker compose up -d
```

`20261105-180736-5271a4a` is the worked example: the first tag published by CI. On the host the
image is pulled from GHCR rather than built. The tag format, the pull, the migration step and the
smoke check are in [release-process.md](release-process.md) §2–§3.

## 4. What the app receives and what it does on start

Compose gives the `app` service exactly these Stockroom settings (from `compose.yaml`):

| Variable                 | What Compose sets                                                      | Note                                                                                                     |
| ------------------------ | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `STOCKROOM_DATABASE_URL` | the in-network DSN to the `db` service on `5432`, database `stockroom` | declared in `compose.yaml`; its credentials are throwaway local-development values and stay in that file |
| `STOCKROOM_ENVIRONMENT`  | `development`                                                          | the same value locally and on the host, because both use this file                                       |

`STOCKROOM_COMMIT` and `STOCKROOM_BUILD_TIME` are not set anywhere in `compose.yaml` or the
`Dockerfile`, which leads to the second verified fact below.

The image's own `CMD` is the startup contract. Read from the `Dockerfile`, it runs, in order:

1. `alembic upgrade head`
2. `python -m backend.db.seed` (the idempotent seed)
3. `uvicorn backend.main:app --host 0.0.0.0 --port 8000`

So `docker compose up -d` migrates and seeds by itself. **Verified:** a fresh local stack in this
session ran those three steps before serving, and a restart on a populated volume comes up the
same way. Nothing outside the container applies migrations.

Two facts are read from the code rather than assumed:

- **The image self-migrates and self-seeds on start.** The `Dockerfile` `CMD` chains
  `alembic upgrade head`, the seed and uvicorn, so starting the container is the migration step.
- **`/api/version` does not identify the tag today.** `backend/config.py` defaults `commit` and
  `build_time` to `unknown`, and neither `compose.yaml` nor the `Dockerfile` sets
  `STOCKROOM_COMMIT` or `STOCKROOM_BUILD_TIME`. The endpoint therefore answers
  `{"version":"0.1.0","commit":"unknown","build_time":"unknown","environment":"development"}`.
  Use the image reference in `docker compose ps` or `docker inspect` to identify a release, not
  `/api/version`.

## 5. Health, smoke and logs

`/healthz` checks liveness and the database. It returns `{"status":"ok","db":"ok"}` when
`SELECT 1` succeeds, and a `503` `application/problem+json` body when the database is unreachable
(`backend/api/health.py`). The image declares a `HEALTHCHECK` that calls it every 5 seconds after
a 15-second start period, so `docker compose ps` shows `(healthy)` once the app is ready.

`scripts/release-smoke.sh` is the post-start check. With no argument it targets
`http://localhost:8000`; one optional argument replaces that base URL. It performs all three
checks and exits non-zero if any fails:

1. `GET /healthz` returns `"status":"ok"` and `"db":"ok"`.
2. `GET /` returns `200` with `text/html` and the built UI's app root element.
3. `GET /api/version` answers with the `version` and `commit` fields.

Read the logs from the service:

```bash
docker compose logs --tail=100 app
docker compose logs --tail=100 db
```

Add `-f` to either command to follow. The app log shows Alembic, the seed and uvicorn; the `db`
log shows PostgreSQL startup and connection handling.

## 6. Data and the volume

PostgreSQL stores its data in the named volume `stockroom-db`, mounted at
`/var/lib/postgresql/data`. Compose prefixes the volume with the project name, so the Docker volume
is `stockroom_stockroom-db` by default and follows the project name when `-p` is used.
`docker compose down` leaves the volume in place; `docker compose down -v` deletes it and the next
start migrates and seeds an empty database.

Backup and restore are not part of this document; risk R3 in [_docs/plan.md](plan.md) tracks the
restore rehearsal.

## 7. What is deliberately not in the stack

The app has no authentication ([handoff](handoff.md) D13), there is no separate frontend
container or CDN (handoff D9), and there is no public URL, DNS or TLS step in the repository
(handoff §6, open item O3). Those are host concerns outside this Compose stack.
