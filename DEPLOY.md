# Deploying — hosted link

Backend on **Render**, frontend on **Vercel**. Roughly 10 minutes, no card required on
either free tier.

The order matters: each side needs the other's URL, so deploy the backend first, then
the frontend, then hand the frontend's origin back to the backend.

```
1. Render  (backend)  ─►  https://<api>.onrender.com
2. Vercel  (frontend) ─►  NEXT_PUBLIC_API_URL = the Render URL
3. Render  again      ─►  CORS_ORIGINS = the Vercel URL
```

Skipping step 3 leaves a frontend that loads but cannot call the API — the browser
blocks it, and every request fails with "Could not reach the API".

---

## 1. Backend → Render

1. <https://dashboard.render.com> → **New** → **Blueprint**
2. Pick this repository. Render reads [`render.yaml`](render.yaml) and proposes a
   Docker web service named `data-qa-api`.
3. It will ask for the one value marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `CORS_ORIGINS` | `http://localhost:3000` for now — corrected in step 3 |

4. **Apply**. The first build takes ~5 minutes (it installs DuckDB and pandas).
5. Copy the service URL, e.g. `https://data-qa-api.onrender.com`, and confirm it is up:

   ```bash
   curl https://data-qa-api.onrender.com/health
   ```

   Expect `{"status":"ok"}`.

Everything else — Docker path, `/health` check, single instance, session TTL — is
already in the blueprint.

## 2. Frontend → Vercel

The repository is a monorepo, so the root directory has to be set or the build will
not find the app.

1. <https://vercel.com/new> → import this repository
2. **Root Directory:** `frontend` ← required
3. Framework preset: **Next.js** (detected automatically)
4. Add one environment variable:

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | your Render URL, no trailing slash |

   This is inlined at **build** time, not read at runtime, so changing it later means
   redeploying — it cannot be fixed by editing the variable alone.
5. **Deploy**, then copy the resulting origin, e.g. `https://fde-data-qa.vercel.app`.

## 3. Tell the backend about the frontend

Back in Render → your service → **Environment**:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | your Vercel origin, e.g. `https://fde-data-qa.vercel.app` |

No trailing slash; comma-separated if you want to keep `http://localhost:3000` for
local development. Saving triggers a redeploy. Once it is live, open the Vercel URL.

---

## The model key

The blueprint deliberately ships **no `GROQ_API_KEY`**. A public instance with a shared
key means strangers spend it, so instead each visitor supplies their own in the
settings panel: it is verified, held in memory for that session only, never written to
disk, and never returned to the browser. One visitor's key is invisible to another.

So the flow for whoever opens the link is:

1. Get a free key at <https://console.groq.com>
2. Open the app → gear icon → paste it under **Your Groq API key** → Save
3. Upload files and ask questions

If you would rather the link work with no setup at all, add `GROQ_API_KEY` in Render's
dashboard (**Environment** → the value is stored as a secret). Use a **freshly created**
key — never one that has been pasted into a chat, an issue, or a commit.

## Free-tier behaviour worth knowing

- **The backend sleeps.** Render free instances spin down after ~15 minutes idle, and
  the next request takes ~50 seconds to wake them. The first click on a cold link looks
  like a hang. Warm it up before a demo:

  ```bash
  curl https://data-qa-api.onrender.com/health
  ```

- **Sleeping loses uploads.** Sessions live in the backend process, so a spin-down
  clears them. The UI says "Session not found or expired" and the files need
  re-uploading. `SESSION_TTL_MINUTES` is set to 30 rather than the local default of 120
  so the advertised behaviour matches what the platform actually delivers.

- **Ollama is not available.** Nothing on a hosted free tier can run a local model, so
  the deployed instance is hosted-only. The offline path is for a local or on-prem run —
  see the README.

- **Uploads are capped at 25 MB** per file here (50 MB locally), since free instances
  have less memory to hold the parsed tables.

## Alternatives to Render

Any platform that runs a **persistent process** works; the requirement is not Render
specifically. Fly.io and Railway both do, and the `backend/Dockerfile` needs no changes.

Serverless platforms — including Vercel's own Python functions — do **not** work for the
backend. Each session owns a live in-process DuckDB connection holding the uploaded
tables, and on serverless consecutive requests can land on different instances, so an
upload would disappear before the next question. Making it serverless-ready means moving
session state to Redis and DuckDB to shared storage first.
