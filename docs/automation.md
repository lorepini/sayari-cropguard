# Pipeline Automation — Setup Guide

The Sentinel-2 pipeline now runs automatically via GitHub Actions
(`.github/workflows/sentinel_refresh.yml`). This document is the one-time
setup checklist plus how to monitor / debug.

## What it does

- Runs **once a day at 03:00 UTC** (22:00 Lima — chosen so scenes from that
  day's Sentinel-2 pass over Lambayeque (~15:30 UTC) have time to publish to
  CDSE).
- Calls `python pipeline.py --scenes 1`. The pipeline:
  - Searches CDSE OData for the latest cloud-free L2A scene (≤25% cloud)
  - Downloads the .SAFE zip (~1 GB), extracts bands
  - Computes NDVI/NDWI/EVI per community polygon
  - Scores stress, generates Spanish alerts (LLM if `ANTHROPIC_API_KEY` set,
    template fallback otherwise)
  - Updates `data/processed/index_history.parquet`
- Records a UTC timestamp to `data/processed/.last_pipeline_run.txt`.
- If the parquet changed, commits and pushes to `main`. Render auto-deploys
  on push (already wired via `render.yaml`).
- If anything fails, opens a GitHub issue tagged `pipeline-failure` so the
  team is notified.

## One-time setup

### 1. Add repository secrets

Go to **Settings → Secrets and variables → Actions** in the GitHub repo and
add these three secrets:

| Secret name          | Where to get it |
|----------------------|---|
| `CDSE_USER`          | The email used at https://dataspace.copernicus.eu |
| `CDSE_PASSWORD`      | The password for that account |
| `ANTHROPIC_API_KEY`  | https://console.anthropic.com — Settings → API Keys. **Optional** — pipeline still runs without it (alerts use the template fallback) |

### 2. Verify the workflow has push permission

In **Settings → Actions → General → Workflow permissions**, make sure
"**Read and write permissions**" is selected. (This is the default for new
repos but worth confirming.)

### 3. Trigger the first run manually

In the **Actions** tab, click "Sentinel-2 data refresh" → "Run workflow" on
the `main` branch. This validates the secrets without waiting for the cron.

A successful first run will:
- Take 5–15 minutes
- Either commit a new `index_history.parquet` row (if a fresh scene was
  available) or log "No data changes" (if the latest scene was already
  processed)
- Trigger Render to redeploy with the new data

## Monitoring

- **Dashboard freshness card** — the AI Summary panel on the Pozos tab
  shows "🛰️ Última actualización satelital: hace X". Green if <36 h,
  amber if <7 d, red if older.
- **GitHub Actions tab** — every run is logged. Failed runs auto-create an
  issue.
- **Issues tab** — search for label `pipeline-failure` to see all historical
  failures.

## Common failures and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `[auth] Login failed (401)` | CDSE password rotated | Update the `CDSE_PASSWORD` secret |
| `No scenes found for AOI/date range` (multiple days in a row) | Persistent cloud cover | None — wait. Bumping `MAX_CLOUD_COVER` in `config.py` only helps for a few extra scenes. |
| `403 Forbidden` on git push | Workflow lost write permission | Re-check Settings → Actions → Workflow permissions |
| `ModuleNotFoundError: rasterio` | `requirements.txt` out of date | Add the missing dep, push to `main` |
| Workflow runs but parquet never updates | Pipeline silently produces `status=None` for the new row | Known issue — see backlog. Patch in `callbacks.py` masks it but root cause is in `score_communities` / `classify_stress`. |

## Cost

GitHub Actions free tier: 2,000 minutes/month for public repos (unlimited
for public; this repo is currently public). Daily run uses ~15 min × 30 days
= ~450 min/month. Plenty of headroom.

CDSE: free with registration, no quota for individual researchers.

Anthropic API (Claude Haiku for alerts): ~$0.10/year at this volume.

## Disabling

If you need to pause the cron (e.g. during a demo to avoid mid-presentation
re-deploys), either:
- Comment out the `schedule:` block in the workflow YAML, or
- Disable the workflow from the Actions tab (one click)

`workflow_dispatch` (manual trigger) keeps working even if the schedule is
disabled.
