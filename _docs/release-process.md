# Release process

The release path is: build once in CI, then a human runs the same image tag on the self-hosted
Compose host. **CI never deploys; a human runs the release.** There is no second build on the
host — the tag that passed CI is the tag that runs. [deployment.md](deployment.md) describes the
running stack; this document is the human procedure.

## 1. Build once in CI

The `release` job in `.github/workflows/ci.yml` runs on a push to `main` or a manual dispatch,
after the `test` and `integration` jobs pass. It computes one tag, builds one image, pushes it to
GHCR, and refuses to overwrite a tag that already exists. Pull requests build the image and never
publish. The job summary records the tag, the local image id and the pushed digest.

CI stops at the pushed tag. It does not reach the host and does not change what is running there.

## 2. Tag format

One shape, defined here and nowhere else:

`YYYYMMDD-HHMMSS-<7-hex-sha>`

That is a UTC timestamp followed by the first seven hex characters of the commit SHA, published as
`ghcr.io/cancinoray/stockroom:<tag>`. The workflow derives it with `date -u +%Y%m%d-%H%M%S` and
`${GITHUB_SHA::7}`, and rejects a value that does not match `^[0-9]{8}-[0-9]{6}-[0-9a-f]{7}$`.
The worked example used throughout the docs is
`ghcr.io/cancinoray/stockroom:20261105-180736-5271a4a`, the first tag CI published.

## 3. Release procedure (human, on the host)

Run these from the repository root on the host, where `compose.yaml` lives. `<new-tag>` is the tag
from the release job summary.

Pull the new tag:

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<new-tag> docker compose pull app
```

The pull is a release step, not a rollback step; keep it outside any rollback clock.

Migrate ahead of the swap:

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<new-tag> docker compose run --rm app alembic upgrade head
```

This runs the new image's migrations in a one-off container while the previous version is still
serving. The container would also migrate on start, because its `CMD` runs `alembic upgrade head`
first. Running it separately first changes where a bad migration fails: the one-off container
fails **before traffic moves**, with the old version still answering, instead of taking the new
version down during the swap.

Swap in the new tag:

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<new-tag> docker compose up -d
```

Compose recreates `app` with the new tag. Wait for `docker compose ps` to show `(healthy)` before
the smoke check; the image healthcheck calls `/healthz`.

Smoke the release:

```bash
scripts/release-smoke.sh
```

It defaults to `http://localhost:8000` and accepts one optional base URL if the host is reached by
another address. It must exit `0` with all three checks: `/healthz` with `"db":"ok"`, `GET /`
serving the built UI, and `/api/version` answering.

Confirm which artifact is running:

```bash
docker compose ps
docker compose ps -q app | xargs docker inspect --format '{{.Config.Image}}'
```

`docker compose ps` prints the image reference in its `IMAGE` column; the second command reads the
reference from the container itself. Both must show `<new-tag>`. `/api/version` is not an identity
check today: it reports `commit` and `build_time` as `unknown` (see
[deployment.md](deployment.md) §4).

## 4. Why the swap runs the pulled image, not a local build

`compose.yaml` declares both `image: ${STOCKROOM_IMAGE:-stockroom-app:local}` and `build:`. When
the tag named by `STOCKROOM_IMAGE` is already present in the local image store, `docker compose up
-d` reuses it: no `--build` is passed, so Compose does not rebuild the checkout. This is the
`--no-build` behaviour the release and rollback rely on, and it is why the pull in §3 happens
first. If the tag were absent, `up` would build an image from the `build:` section (the
`--no-build` flag exists precisely to prevent that), and the stack would run a locally built
artifact that is not the released tag.

The rehearsal proves which artifact ran by matching the running container's `.Image` id to the
pulled tag's image id, rather than trusting the tag printed by a shell variable.

## 5. Rollback

From the repository root on the host, one command returns the stack to the previous tag:

```bash
STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<previous-tag> docker compose up -d
```

`<previous-tag>` is the tag that ran before this release. It is already in the host's image store
because it was pulled when it was released. If it is not present, pull it first with
`STOCKROOM_IMAGE=ghcr.io/cancinoray/stockroom:<previous-tag> docker compose pull app` and keep that
pull outside the rollback clock; the pull belongs to the earlier release.

Verify the rollback:

```bash
docker compose ps
docker compose ps -q app | xargs docker inspect --format '{{.Config.Image}}'
scripts/release-smoke.sh
```

`docker compose ps` and `docker inspect` must show `<previous-tag>`, not the tag that was rolled
back from and not a local build. The smoke must exit `0` with all three checks.

Measured in the engineer rehearsal for issue #12: **17.591 s** (`time` real) from invoking the
rollback command to `scripts/release-smoke.sh` exiting `0` on a local Compose stack, with the
previous tag already in the image store. The budget is 120 s. A human rehearsal is a separate
sign-off recorded on the issue.

### Database caveat

Migrations are forward-only. `alembic downgrade` is not part of the rollback. Because the
container runs `alembic upgrade head` on start, rolling back across a release that shipped a
migration fails at startup with an unknown revision: the older image does not contain the newer
revision recorded in the database. **That case is not covered by this rollback.** It needs a
forward fix or a restore, and that is a separate decision. The one command above covers rollback
between releases whose schema is unchanged.

## 6. Credentials

GHCR is public-read today. An anonymous `docker manifest inspect` of a release tag returns the
manifest, and a host pulls without logging in. If the package stops being public, log in on the
host only, with a token scoped to `read:packages`, using `docker login ghcr.io`. That is the
fallback, not the normal path.

Credentials stay on the host. No token, `.env` file or `docker` `config.json` sample belongs in the
repository. CI authenticates with its own workflow token to push; that token is never copied to the
host.
