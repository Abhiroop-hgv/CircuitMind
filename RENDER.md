# Deploying to Render

`render.yaml` in the repo root is a Blueprint: it describes a Postgres database
and the two services (API, dashboard) so Render can create all three in one
pass instead of you clicking through three separate "New +" flows.

I can't do the actual deploy for you — it needs your Render account and a
Groq API key typed into Render's own dashboard, not handed to me. Here's the
whole thing, and it's short.

## 1. Deploy the Blueprint

1. [render.com](https://render.com) → sign in (or sign up) → **New +** → **Blueprint**.
2. Connect your GitHub account if you haven't, then pick `Abhiroop-hgv/CircuitMind`.
   (Grant Render access from the GitHub side when prompted — that's between
   you and GitHub, not something to paste anywhere.)
3. Render reads `render.yaml` and shows you three resources:
   `circuitmind-db` (Postgres), `circuitmind-api`, `circuitmind-web`.
4. It will ask for **`GROQ_API_KEY`** — the one env var marked `sync: false`
   in the blueprint, meaning "don't store this in the repo, ask the human".
   Paste your key from [console.groq.com](https://console.groq.com) (free tier).
5. **Apply**. Render provisions the database, then builds and deploys both
   services. First deploy takes a few minutes — the API's `preDeployCommand`
   builds the schema and seeds the demo data as part of it, so by the time it
   goes live there's already a recommendation waiting.

## 2. Open it

`circuitmind-web`'s dashboard page shows its URL — something like
`https://circuitmind-web.onrender.com`. Open it, sign in with any name.

## 3. If a service name was already taken

Render service names are global. If `circuitmind-api` or `circuitmind-web` is
taken, Render will suffix yours (`circuitmind-api-a1b2`) during Apply. The two
services need to know each other's *actual* URL, and `render.yaml` guesses the
un-suffixed one:

- `circuitmind-web`'s **`NEXT_PUBLIC_API`** env var must equal the API's real
  URL. This is compiled into the page at build time (Next.js), so after
  changing it you need a new **build**, not just a restart — the Environment
  tab's save-and-redeploy does this for you.
- `circuitmind-api`'s **`CORS_ORIGINS`** env var must equal the web service's
  real URL, or the browser will block every request as cross-origin. A
  restart is enough for this one (no build step reads it).

## 4. What "free plan" means here

- **Database**: Render's free Postgres is deleted **30 days** after creation
  unless you upgrade the plan. Fine for a hackathon judged this week; not
  something to leave unattended for a month.
- **Both services**: free web services spin down after 15 minutes with no
  traffic and take ~30-50s to wake on the next request. The API keeps itself
  pinged (`_keep_alive` in `api/main.py`, using Render's own
  `RENDER_EXTERNAL_URL`) but Render's free tier sleeps regardless of that —
  the ping just means *if* it's awake, it stays awake a little longer, not
  that it never sleeps. If you're demoing live to judges and a cold start
  would be embarrassing, bump `plan: free` to `plan: starter` for
  `circuitmind-api` and `circuitmind-web` in the dashboard (or in
  `render.yaml` before the next deploy) — a few dollars for the day, no sleep.

## 5. Re-seeding

Every deploy re-runs `init_db.py` (rebuild schema + deterministic seed) and
`demo.py --offline` (produce the STM32 recommendation) before going live, so
pushing to `main` — or clicking **Manual Deploy** — puts the demo back to its
known-good state. That also means an approval a judge makes during a live demo
won't survive the *next* deploy; that's expected, not a bug (see README's note
on `scripts/reset_approval.py` for the same idea locally).

The second demo scenario (SH-100 flash substitution) isn't in the automated
seed — it's `scripts/run_bom_intake.py` then `scripts/make_bom_split_po.py`,
run once against a live deploy the same way you'd run them locally, pointed at
`DATABASE_URL` from the Render dashboard's Postgres **Connect** tab. Add them
to `preDeployCommand` in `render.yaml` if you want it seeded automatically on
every deploy too.
