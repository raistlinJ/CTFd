# Week 7 CTFd Agent

The customized CTFd 3.8.9 build, including solve retraction, runs at
<http://127.0.0.1:8000>. Its source checkout is
`/Users/jcacosta/Documents/GitHub/CTFd`, base commit `1c19ae18`, with the empty-prerequisite backup-import fix in
`CTFd/utils/exports/__init__.py` and image `teaching-ctfd:import-fix-20261026`.

Five visible challenges and eight public attachments are installed:

| Category | Independent challenge chains |
| --- | --- |
| Week 7 - CTFd Agent | 01 Records room → 02 Encoded ticket; 03 Night journal → 04 Verified handoff → 05 Close the investigation |

Participants initially see only challenges 01 and 03. Each challenge is worth
10 CTFd points, for 50 submission points across all five. All five share one category and retain two independent prerequisite chains.

All five challenges allow any solving method for submission credit. Each whole
challenge completed autonomously from retrieval through accepted submission earns
10 additional homework points (50 maximum), giving 100 points total.

Private login passwords and API tokens are in
[.data/teaching/credentials.json](.data/teaching/credentials.json), protected by
file mode 600. Those are the original exported-event credentials: account `0` is `instructor`
(administrator). The preserved live event currently has one admin, `acosta`.
Importing the original Week 7 event backup restores its original accounts, including
`instructor`; its saved password was verified against that backup. Registration is
private. Create additional users through the administrator interface as needed.

From this checkout:

```sh
docker compose -f compose.teaching.yml up -d --wait
docker compose -f compose.teaching.yml logs --tail 100 ctfd
docker compose -f compose.teaching.yml stop
```

The MariaDB database, attachments, and logs use Docker named volumes, and the signing
secret is stored in `.data/teaching/server.env`. Container recreation preserves
the event. Keep these volumes and the environment file when restarting or
backing up the deployment. `docker compose down -v` deletes the stored event.
The published port is bound to this computer's loopback interface.

The local source now includes an administrator-controlled **Users Can Clear
Submissions** setting (`allow_solve_retraction`), also exposed in DeployForge's
CTFd Manager. Rebuild `Dockerfile.teaching` and recreate the web service to deploy
this change. It defaults to disabled when the setting has not previously been
saved. Enable it under **Config → Challenges** or from the Manager after a refresh.
This controls the existing **Retract solve** action; it preserves failed attempts,
hint purchases, and awards. No database migration is required.

The installed pack comes from the Fall teaching workspace under
`cs5390-agentic/Week 7 - ReAct/homework/ctfd-agent/instructor/challenge-pack`.
Only its eight listed public attachments were uploaded. The original definitions
remain hidden by default on disk; this deployment deliberately makes the
installed challenges visible after configuring their requirements.

Live integration evidence is stored in `.data/teaching/live-validation.json`:
all attachments were downloaded, answers were derived from those bytes, both
chains were solved, tasks 3–5 were completed before tasks 1–2, locked details
were rejected, and wrong submissions unlocked nothing. All five solves were
then retracted through this checkout's custom API. This was an integration
check, without a model. The regular participant account remains unused.

## Backup-import repair and migration (October 26, 2026)

The live instance now uses MariaDB 10.11 through the `database` service. Database
credentials are in `.data/teaching/database.env` and `.data/teaching/mariadb.env`,
both mode 600. The signing secret, port, uploads and logging volumes are retained.
Only one CTFd web service runs. `Dockerfile.teaching` extends the original custom
image with the import fix; `docker compose -f compose.teaching.yml up -d --build --wait`
rebuilds it without changing the original base image.

The importer now JSON-serializes empty prerequisite dictionaries in its existing
PyMySQL retry path. This fixes `dict can not be used as parameter` for challenges
without prerequisites. Full-backup imports are supported on the new MariaDB
backend. They replace destination event data and accounts.

The migration exported the stopped live SQLite instance, imported that exact
snapshot into MariaDB, and compared every nonempty table and attachment. Five
challenges, eight exact attachment byte streams and the existing `acosta` admin
were preserved. Import/startup regenerates theme/version, plugin-migration and
update-check configuration. Verification is in
`.data/teaching/migration-20261026/validation.json`.

Rollback materials are private under `.data/teaching/migration-20261026/`: the
pre-migration event export, original Compose file and prior importer source.
The original `teaching-ctfd_database` SQLite volume is untouched. To deliberately
roll back, stop the current web service, copy `compose.sqlite.yml` back to
`compose.teaching.yml` in this repository root, and start that Compose configuration.
This restores the pre-migration SQLite event, not any later MariaDB changes.
Do not remove either database volume until rollback is no longer needed.

## Navigation connection cleanup (October 27, 2026)

A captured Chrome navigation waited about 57 seconds before sending its request;
CTFd responded in about 18 ms once the request arrived. Opening DevTools cleared
the stall. This establishes a browser-side delay but does not prove its cause.

The core theme now closes its notification event stream on `beforeunload` and
`pagehide`, and reconnects it when a page is restored from the history cache.
This avoids relying on `unload`, which Chrome reported as prohibited. This is a
targeted mitigation; recurrence in the original browser still needs monitoring.
`Dockerfile.navigation` applies only the template change to a working image,
without rebuilding theme bundles or replacing backend files from this checkout.

Run the lifecycle regression checks with
`node --test tests/frontend/test_events_lifecycle.cjs`. Browser verification is
recorded in `.data/teaching/navigation-fix-validation.json`. The prior local image
is retained as `teaching-ctfd:pre-navigation-cleanup-20261027`; event data and the
UTEP deployment are unchanged by this local update.

The original `teaching-ctfd:1c19ae18` base image is no longer present locally,
and the working image's backend differs from this checkout. Use the template-only
overlay for this update:

```sh
docker build --build-arg NAVIGATION_BASE_IMAGE=teaching-ctfd:pre-navigation-cleanup-20261027 -f Dockerfile.navigation -t teaching-ctfd:import-fix-20261026 .
docker compose -f compose.teaching.yml up -d --no-deps --no-build --wait ctfd
```
