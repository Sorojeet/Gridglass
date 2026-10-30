# Deploying Gridglass

Gridglass ships as one Docker image: Flask + gunicorn, non-root, with a health check at `/healthz`. Any host that runs a Dockerfile works. Below are the two easiest options.

## 1. Put the code on GitHub

```bash
cd gridglass
git init && git add . && git commit -m "Gridglass 1.0"
git branch -M main
git remote add origin https://github.com/<you>/gridglass.git
git push -u origin main
```

The CI workflow starts on this first push. It runs:
- the unit tests
- the browser tests
- a build of the Docker image, with the browser suite run against the real container

Wait for the green tick before deploying.

## 2a. Render (recommended)

1. Sign in at render.com with GitHub.
2. Click **New → Blueprint** and pick the `gridglass` repo. Render reads `render.yaml`, which sets the Docker runtime, the Singapore region (closest to India), the health check and the environment variables.
3. Click **Apply**. The first build takes about 3–5 minutes. You'll get a URL like `https://gridglass.onrender.com`.
4. Optional: add a custom domain under **Settings → Custom Domains**. Render handles the HTTPS certificate.

Plans:
- **Free** works but sleeps after 15 idle minutes; the first visit afterwards takes ~30 s.
- **Starter** stays awake.

With 512 MB of RAM, set `WEB_CONCURRENCY=1` so one large 50 MB file always has room. With 1 GB or more, keep 2.

## 2b. Railway

1. Go to railway.com, then **New Project → Deploy from GitHub repo → gridglass**.
2. Railway detects `railway.json` and builds the Dockerfile.
3. Go to **Settings → Networking → Generate Domain**.
4. Add the variable `TRUST_PROXY=1`. The Dockerfile already sets it, but it doesn't hurt.

## 3. Check the live site

```bash
curl https://<your-url>/healthz      # {"status":"ok", ...}
E2E_BASE_URL=https://<your-url> pytest -m e2e -k "home or remove_duplicates or convert"
```

The second command runs the real browser tests against your live site. Keep it to a few tests (`-k`), so you stay under the upload rate limit.

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `MAX_UPLOAD_MB` | 50 | Largest file a user can upload |
| `FILE_RETENTION_MINUTES` | 60 | When uploads are deleted |
| `TRUST_PROXY` | 1 in Docker | Number of proxies in front of the app (Render/Railway: 1). Needed for correct client IPs and HTTPS. |
| `WEB_CONCURRENCY` | 2 | gunicorn worker processes. Use 1 on 512 MB plans. |
| `POLARS_MAX_THREADS` | 2 | CPU threads per worker for data work |
| `RATE_LIMIT_UPLOADS` | `10 per minute; 60 per hour` | Per visitor IP |
| `RATE_LIMIT_EXPORTS` | `30 per minute; 300 per hour` | Per visitor IP |
| `RATE_LIMIT_API` | `600 per minute` | Everything else under `/api` |
| `RATELIMIT_STORAGE_URI` | `memory://` | Use `redis://…` when running several instances |
| `DATA_DIR` | `/tmp/gridglass` in Docker | Where uploads live while they're being worked on |
| `LOG_LEVEL` | info | gunicorn log level |

## Notes

- **Storage.** Uploads live for an hour at most, so the container's own disk is enough. A redeploy only loses files that are being worked on at that moment.
- **Several instances.** If you run more than one instance, they need a shared `DATA_DIR`, such as a mounted volume. Without one, a user's next request can land on a server that doesn't have their file. You also need `RATELIMIT_STORAGE_URI` pointing at Redis, so limits are shared.
- **Privacy.**
  - Upload ids are removed from access logs.
  - The API is never cached.
  - Exports are deleted as soon as they're sent.
  - Users can delete their file straight away with Start over.
- **Updates.** Push to `main`. CI tests it, and Render or Railway redeploy automatically.
