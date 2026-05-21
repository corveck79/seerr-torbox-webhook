# Mycelium — Session Handoff

Carry this into the next chat so context isn't lost. Last updated: 2026-05-21.

## What this project is

Self-hosted media pipeline (Flask + SQLite + React SPA) that turns watchlist
clicks into Jellyfin-ready `.strm` files streaming from TorBox. Runs as one
Docker container on a Synology NAS.

- **Live deployment (source of truth):** NAS at
  `/volume1/docker/jelly-stack/webhook` — this directory IS the git repo,
  on branch `main`, remote `github.com/corveck79/mycelium`.
- **Update flow on NAS:** `git pull origin main && docker compose up -d --build`.
  Working tree is clean; data lives in `./data` (DB, `.strm`, settings) and
  survives rebuilds.
- **App URLs:** dashboard `http://10.0.0.10:8088/ui`, SPA `http://10.0.0.10:8088/app/`.
  Jellyfin at `http://10.0.0.10:8096`.

---

## Current state (end of session 2026-05-21)

Everything is on `main`. The NAS needs a `git pull + rebuild` to pick up recent changes.

### What to do right now on the NAS

```bash
git pull origin main
docker compose up -d --build
```

After rebuild:
1. **Admin → Maintenance → Clean up duplicate strm files** — removes extra `.strm` per
   folder (fixes the 402 vs 232 Jellyfin entry count).
2. **The Amateur**: try the new re-resolve endpoint instead of manual SQL:
   `curl -X POST http://localhost:8088/ui/api/virtual-items/227a6d344f04441c/re-resolve`
   The known-hash RD fast path should now resolve it.
3. Jellyfin **Scan All Libraries**.

### Multi-user context (revealed this session)

Repo is **public on GitHub** and 6-8 other users run this Plex/ARR stack. This raised the
bar on reliability: a single failed playback must NOT delete content for everyone. The
`.strm`-on-first-miss behavior was changed accordingly (see decisions table).

---

## Changes this session (2026-05-21) — RD-first + stability sprint

**RD as primary debrid, TorBox as fallback** (`e5d228e`)
- `_search_best_cached_release()` now checks RealDebrid cache first, TorBox second,
  returns `(hash, magnet, provider)` tuple.
- `_materialize_locked` has separate RD and TorBox code paths; either can switch provider
  if the search returns a different one.
- `debrid.check_cached_multi()` always queries RD when configured (no feature gate).

**Zilean in catbox search path** (`7cb2d08`)
- Zilean is queried before Torrentio in `_search_best_cached_release` when `ZILEAN_ENABLED`.

**Known-hash RD fast path + don't delete .strm on first miss** (`3ddb379`)
- When `info_hash` is in the DB but Torrentio returns 0 results (e.g. The Amateur), RD is
  checked directly for that hash before a full search. Solves "Torrentio finds nothing but
  the torrent is cached".
- `_remove_strm()` is no longer called on the first "no cached release" miss. Instead a 6h
  fail cooldown is set and the .strm stays; the scheduled repair job handles real cleanup.
  Protects the shared library from transient API failures.

**Persistent playability state + structured reason codes + re-resolve** (`a138a0a` + db/catbox)
- New `playability_state` table: `content_key` (imdb_id, or `imdb_id:SxxEyy` for episodes),
  `status` (unknown/playable/degraded), `last_ok_provider`, `consecutive_failures`,
  `last_fail_reason`. Survives container restarts (the in-memory `_fail_cache` does not).
- Reason code constants in catbox.py: `TORRENTIO_EMPTY`, `NO_CACHED_RELEASE`, `RD_429`,
  `TB_429`, `WAIT_TIMEOUT`, `NO_FILE`, `UNKNOWN_TOKEN`, `ADD_FAILED`, etc. Written to
  `playability_state.last_fail_reason` on every failure path.
- `POST /ui/api/virtual-items/<token>/re-resolve`: clears in-memory + persistent fail
  state, triggers fresh materialize (50s timeout). Replaces manual SQL debugging.
- `GET /ui/api/playability-state`: lists degraded items with 3+ consecutive failures.

**Series backfill via lazy .strm** (`52c5647`)
- `monitor.run_series_backfill()` chains `arr_import.import_sonarr()` + `run_series_check()`.
- In catbox mode `_retry_episode` writes a lazy `.strm` (token only) instead of eagerly
  adding to TorBox — no quota consumed until someone actually plays.
- Admin "▶ Sync all series + episodes" button → `POST /ui/api/series-backfill`.

**Duplicate .strm fix** (`971d53e`)
- `_do_rename` now renames internal `{stem}.strm`/`.nfo` files when a folder is renamed.
- `cleanup_duplicate_strms()` keeps the .strm matching the folder name, removes the rest.
- Admin "Clean up duplicate strm files" button → `POST /ui/api/cleanup-duplicate-strms`.

### Codex refactor plan — what was adopted vs skipped

The full Codex plan (provider health scoring, playback_events audit table, processor
preflight, frontend status badges, full uniform provider contract) was assessed as
mostly overkill for an 6-8 user setup. **Adopted** the high-value subset: persistent
`playability_state`, structured reason codes, and the re-resolve admin endpoint.
**Skipped/deferred**: health-score-based provider selection (RD-first is deterministic
enough), `playback_events` audit table (logs+Prometheus cover it), frontend badges.
A "Re-resolve" button per degraded item in `Admin.tsx` is the next obvious UI add (not
yet built — backend endpoints are live).

---

## Architecture summary

```
User → SPA (/app/) or Seerr webhook → processor.py
  → Zilean (local) + Torrentio (fallback, with browser User-Agent)
  → debrid.check_cached_multi() → pick best CACHED release only
  → catbox.register() → write .strm + .nfo + poster.jpg + fanart.jpg
  → Jellyfin refresh

On play (catbox mode), catbox.materialize(token) — provider-aware:
  RD path (debrid_provider='realdebrid'):
      1. rd_id still downloaded in RD? → get URL → 302 redirect (fast path)
      2. Else → fresh search (RD-first) → add_magnet → wait_until_ready → URL
  TorBox path (default):
      1. torbox_id still live? → requestdl → 302 redirect (fast path)
      2. Else known info_hash in TorBox library? → use it
      3. Else known info_hash cached on RD? → switch to RD, add, serve
      4. Else fresh Zilean+Torrentio search (RD-first, TB fallback) → add → serve
  On miss: 6h cooldown + playability_state='degraded'; .strm KEPT (repair job
           cleans up truly-dead items later). reason_code recorded.
```

**Core invariant (imdb_id is leading):**
- 1 imdb_id = 1 movie folder = 1 .strm — structurally enforced
- Folder name = TMDB canonical title + year (not torrent name)
- No imdb_id → not added to library

**Catbox mode** (`CATBOX_MODE=true` + `CATBOX_LAZY_ADD=true`):
- `.strm` contains `http://10.0.0.10:8088/stream/<token>`
- Token maps to `virtual_items` row (imdb_id + last known torbox_id as shortcut)
- On play: TorBox shortcut first, else fresh Torrentio search — always finds a playable
  release or removes the .strm
- Stored magnet is no longer re-added blindly; Torrentio is always the fallback

---

## Key design decisions made this session

| Decision | Reason |
|----------|--------|
| **No stored-magnet replay** | Dead magnets caused 45s waits → "Playback Failed". Fresh Torrentio search always finds a cached release or removes the film. |
| **imdb_id as primary key** | Folder names from torrent titles caused Cyrillic duplicates, fuzzy dedup failures. TMDB canonical name is deterministic. |
| **_SEARCH_UNAVAILABLE sentinel** | Distinguishes "searched and found nothing" (→ remove .strm) from "couldn't search" (→ keep .strm, retry later). |
| **Shared maintenance lock** | `migrate_to_canonical_names` and `repair_expired_strms` cannot run simultaneously — rename + repair would conflict. |
| **Auto repair every 6h** | Scheduled job recreates missing .strm files automatically; no manual repair needed. |
| **Keep .strm on first miss** | (Changed 2026-05-21) Shared library with 6-8 users — a single failed playback must not delete content for everyone. First miss → 6h cooldown + degraded state; only repair job removes truly-dead items. |
| **RD-first, TB fallback** | TorBox CDN links were observed failing in Stremio while RD links worked. RD is now primary; TB is fallback. |
| **Known-hash RD check** | Torrentio returns 0 results for some films (The Amateur) even though the torrent is RD-cached. Check the stored hash against RD directly before a full search. |
| **Persistent playability_state** | In-memory fail cache resets on restart → Jellyfin scan re-hammers RD/TB. DB-backed state survives restarts and powers the re-resolve / degraded-items endpoints. |
| **Jellyfin NFO saver = OFF** | Mycelium writes .nfo with imdb_id. Jellyfin NFO saver would overwrite them. |

---

## All changes shipped this session (all on `main`)

| Commit | Change |
|--------|--------|
| `a709735` | Maintenance lock: migrate + repair cannot run simultaneously |
| `b11a71e` | **imdb_id as primary key**: `_canonical_movie_folder()`, `_find_movie_folder_by_imdb()`, update `create_lazy_movie_strm()`, `migrate_to_canonical_names()`, `db.update_virtual_strm_path_prefix()`, Admin "Migrate to canonical names" button |
| `a4ecf65` | Fix aggressive .strm removal (keep .strm when search unavailable); repair Pass 1 dedup skips Cyrillic sibling that already has .strm |
| `45559e8` | Resolve missing imdb_id via TMDB before Torrentio search; `db.update_virtual_item_imdb()` |
| `47b7b7a` | **Rebuild materialize**: live Torrentio search replaces stored-magnet replay; `_search_best_cached_release()` replaces `_find_fresh_cached_release()` |
| `b61b998` | Fix dedup: only skip folder if sibling already has .strm (fixes Cyrillic duplicate getting .strm instead of English folder) |
| `c515215` | Schedule automatic .strm repair every 6h in catbox mode |
| `8bd90cb` | Remove dead .strm from library when no playable release found |
| `ebc346a` | Auto-fallback to fresh Torrentio release when stored magnet is dead |
| `b6b731a` | Failure cooldown in catbox materialize (30s standard / 120s for 429) stops burst retries |
| `bc71df7` | Repair missing .strm files (folders with NFO but no .strm) |

---

## Key files

| File | Purpose |
|------|---------|
| `processor.py` | Request → search → cache-check → catbox lazy register |
| `strm_generator.py` | Write `.strm`/`.nfo`/images; `_canonical_movie_folder()`; `migrate_to_canonical_names()`; `repair_expired_strms()` |
| `catbox.py` | Lazy materialization: TorBox shortcut → Torrentio search → redirect or remove .strm |
| `cleanup.py` | Dedup `.strm`, merge series folders, rename messy names |
| `upgrader.py` | Auto-upgrade quality + season-pack consolidation |
| `torrentio.py` | Torrent candidate fetch + ranking + language filtering |
| `arr_import.py` | Radarr/Sonarr bulk import |
| `auth.py` | Session login, proxy-auth trust, multi-user roles |
| `db.py` | SQLite access: requests, virtual_items, monitored_series, retry_queue |
| `tmdb.py` | TMDB API: search, images, episode stills, IMDb↔TMDB ID mapping |
| `settings.py` | Runtime-editable settings (reads DB first, `.env` fallback) |
| `nfo_generator.py` | Write `.nfo` sidecars + fetch local images |
| `app.py` | Flask app, scheduler, all UI/API endpoints |
| `retry_queue.py` | Exponential backoff retry scheduler |

---

## virtual_items table (catbox mode source of truth)

| Column | Role |
|--------|------|
| `token` | Primary key — goes into .strm URL |
| `imdb_id` | **Leading key** — used for Torrentio search on play |
| `torbox_id` | Cache/shortcut — checked first on play, skips Torrentio if still live |
| `info_hash` | Last known hash — secondary shortcut via `find_by_hash` |
| `magnet` | Stored but no longer blindly re-added (only used if torbox_id/hash shortcut works) |
| `strm_path` | Path on disk — updated by `update_virtual_strm_path_prefix()` on rename |
| `last_played` | Used by idle GC (`release_idle()`) |
| `debrid_provider` | `'torbox'` (default) or `'realdebrid'` — which path materialize uses |
| `rd_id` | RealDebrid torrent id — fast path for the RD provider |

### playability_state table (added 2026-05-21)

| Column | Role |
|--------|------|
| `content_key` | `imdb_id` (movie) or `imdb_id:SxxEyy` (episode) — primary key |
| `status` | `unknown` / `playable` / `degraded` |
| `last_ok_provider` | `torbox` or `realdebrid` — last provider that served successfully |
| `consecutive_failures` | Resets to 0 on success; drives degraded detection |
| `last_fail_reason` | Structured reason code (e.g. `NO_CACHED_RELEASE`, `RD_429`) |

Helpers in db.py: `get_playability_state`, `update_playability_ok`,
`update_playability_fail`, `reset_playability_state`, `get_degraded_items`.

---

## Known remaining issues / next steps

- **The Amateur (2025)**: `imdb_id='tt14961434'`, known good `info_hash=
  'fafbc580d1cb04e00b13b64050375be6021b4536'` (RD-cached 4K). With the known-hash RD fast
  path it should now resolve. If still failing, hit re-resolve:
  `curl -X POST http://localhost:8088/ui/api/virtual-items/227a6d344f04441c/re-resolve`
  and check `playability_state.last_fail_reason` for the structured cause.
- **Re-resolve UI button**: backend endpoints (`/re-resolve`, `/playability-state`) are
  live but not yet wired into `Admin.tsx`. Next obvious UI add.
- **Highlander folder**: has imdb_id `tt1235529` in .nfo but that may be wrong. The 1986
  film is `tt0091203`. Folder is named "Highlander" (no year) as a result.
- **Series in Mycelium**: Sonarr import added 31 series to `monitored_series` DB. Episodes
  appear in Wanted → Episodes tab when found. Series folders appear in Jellyfin once
  episodes are found via Torrentio and .strm files are written.
- **Missing episodes**: "hoe vullen we gemiste afleveringen aan?" — not yet implemented.
- **CATBOX_IDLE_MINUTES**: currently aggressive (60 min default). Recommend setting to
  720 or 1440 in Settings to reduce Torrentio search frequency on play.

---

## Workflow notes / gotchas

- Work directly on `main` (user's preference).
- `data/` is gitignored — can't inspect DB or media from a cloud session.
  Ask user to run `find`/`ls`/`sqlite3` on the NAS when needed.
- POST endpoints are CSRF-protected by default → trigger via dashboard buttons, not curl.
  CSRF-exempt: `/ui/api/repair-strms`, `/ui/api/migrate-canonical`,
  `/ui/api/cleanup-duplicate-strms`, `/ui/api/series-backfill`,
  `/ui/api/virtual-items/<token>/re-resolve`, `/ui/api/requests/<id>/retry`,
  `/ui/api/arr-import/*`.
- Single gunicorn worker, 8 threads → in-process state is shared and safe.
- `settings.get("KEY", default)` reads settings DB first, then falls back to env/config.py.
  Always use `settings.get()` in endpoints — never `config.KEY` directly.
- Jellyfin compose: `/volume1/docker/jellyfin/docker-compose.yml` (separate from app
  compose at `/volume1/docker/jelly-stack/webhook/`).
- CATBOX_HOST must be the externally reachable URL Jellyfin can reach
  (currently `http://10.0.0.10:8088`). This goes into the .strm file itself.
- Jellyfin NFO metadata saver must stay **OFF** — Mycelium owns the .nfo files.
- Media path inside container: `/data/media/movies` and `/data/media/series`.
  On NAS: `/volume1/docker/jelly-stack/webhook/data/media/`.
