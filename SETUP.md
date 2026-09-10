# Setting CircuitMind up on a fresh machine

Everything the app needs to run, from nothing. Windows instructions; the Python
side is identical on macOS/Linux.

---

## 1. Install the four prerequisites

| Tool | Version | Link | Note |
|---|---|---|---|
| Python | 3.10+ | https://www.python.org/downloads/ | tick **"Add python.exe to PATH"** in the installer |
| Node.js | 20+ | https://nodejs.org/ | the LTS build is fine |
| PostgreSQL | 16 or 17 | https://www.postgresql.org/download/windows/ | **write down the `postgres` superuser password you set** |
| Git | any recent | https://git-scm.com/download/win | |

After installing, close and reopen your terminal so `PATH` picks them up.
Check: `python --version`, `node --version`, `psql --version`, `git --version`.

## 2. Get the code

```powershell
git clone https://github.com/Abhiroop-hgv/CircuitMind.git
cd CircuitMind
```

## 3. Add your Groq key

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `GROQ_API_KEY=` to a real key. Get one free at
https://console.groq.com — it's used to read news articles and answer questions
in the assistant. Leave the two `DATABASE_URL` lines alone; the bootstrap script
fixes them.

## 4. Run the bootstrap

```powershell
pwsh scripts/bootstrap.ps1
```

It will:

1. check the four prerequisites are on `PATH`
2. create the `scip` role and database in your local PostgreSQL
3. `pip install -r requirements.txt`
4. build the schema and seed the dummy ERP (`scripts/init_db.py`)
5. create the read-only role the assistant uses (`scripts/create_readonly_role.py`)
6. run the demo chain once so there is a recommendation to look at (`scripts/demo.py --offline`)
7. `npm install` and `npm run build` in `web/`

It asks for the `postgres` superuser password once, in step 2.

## 5. Run the app

```powershell
pwsh scripts/run.ps1
```

Three windows open — PostgreSQL check, the API on :8000, the web app on :3000.
Open **http://localhost:3000** and sign in with any name.

To stop: close the API and web windows. PostgreSQL is your machine's normal
service and can be left running.

---

## If something breaks

- **`psql: could not connect`** — the PostgreSQL service isn't running. Open
  "Services", find `postgresql-x64-17`, Start it. Then re-run the bootstrap.
- **`pip` / `python` not found** — you didn't tick "Add to PATH". Re-run the
  Python installer, choose Modify, enable it.
- **The assistant page errors** — `GROQ_API_KEY` in `.env` isn't a valid key.
- **Numbers look different from the deck** — run `python scripts/verify.py`; the
  seed is deterministic, so a mismatch means the seed didn't finish. Re-run
  `python scripts/init_db.py`.
- **Only one recommendation shows** — that's expected from a clean seed: the
  STM32 export-licence scenario. The BOM/second scenario is generated
  separately; see `scripts/bom_scenario.py` and `scripts/make_bom_split_po.py`.
