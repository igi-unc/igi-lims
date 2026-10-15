# Hosting the demo on Vercel + Supabase

The app runs unchanged on Vercel as a Python (WSGI) function. Vercel has no
persistent disk, so the database lives in Supabase Postgres and uploaded files
in a private Supabase Storage bucket. Visitors need nothing but the URL and the
demo login shown on the login page; only the owner needs the two accounts.

Everything below is done once. Budget about 20 minutes.

**Secrets never go in the repo.** The connection string, the service key, the
Flask secret and the cron secret are typed into the Vercel dashboard only. The
repo already ignores `.env` files, and nothing in the code reads a committed
file for credentials.

## 1. Supabase: create the project

1. https://supabase.com/dashboard → **New project**. Pick the free plan, a
   name (`igi-lims-demo`), a region close to you (US East), and let it generate
   a database password. **Copy the password** now; it is shown only once.
2. Wait for the project to finish provisioning (about a minute).
3. Click **Connect** (top of the page) → **Transaction pooler**. Copy the string.
   It looks like
   `postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:6543/postgres`.
   Replace `[YOUR-PASSWORD]` with the password from step 1 (percent-encode
   `#`, `&`, `?` or spaces if it has any). This is `LIMS_DATABASE_URL`.
   Use the *transaction* pooler on port 6543: it is IPv4 and made for serverless
   functions; the "direct" string is IPv6-only and does not work from Vercel.
4. **Project Settings → API**: copy the **Project URL** (`https://<ref>.supabase.co`)
   and the **service_role** secret key. These are `LIMS_SUPABASE_URL` and
   `LIMS_SUPABASE_SERVICE_KEY`. The service key bypasses row security; it is
   used only server-side and must never be put in a browser or the repo.

The storage bucket (`lims-attachments`, private) is created by the app on the
first upload; nothing to do in the Storage tab.

## 2. Vercel: deploy from GitHub

1. https://vercel.com/new → **Import** the `igi-unc/igi-lims` repository.
   Framework preset: Vercel detects Flask from `app.py`; leave the build
   settings alone.
2. Before clicking Deploy, open **Environment Variables** and add:

   | Name | Value |
   |---|---|
   | `LIMS_DATABASE_URL` | the transaction-pooler string from step 1.3 |
   | `LIMS_SUPABASE_URL` | the project URL from step 1.4 |
   | `LIMS_SUPABASE_SERVICE_KEY` | the service_role key from step 1.4 |
   | `LIMS_SECRET_KEY` | output of `python3 -c 'import secrets;print(secrets.token_hex(32))'` |
   | `LIMS_DEMO_MODE` | `1` |
   | `LIMS_DEMO_PASSWORD` | the password visitors will type on the login page |
   | `CRON_SECRET` | another `secrets.token_hex(32)` value |

3. **Deploy**. The first build takes two or three minutes (allotropy pulls in
   pandas). The site is up when the build finishes, but the database is still
   empty, so the login page will not accept a login until step 3.

## 3. Load the schema and demo data (one command)

The deployed app creates its own tables. Ask it to do so once, from any
terminal, using the `CRON_SECRET` you chose:

```bash
curl -H "Authorization: Bearer <CRON_SECRET>" https://<your-project>.vercel.app/cron/demo-reset
```

It answers `{"reset": true, "participant": "...", "tubes": 43}` after a few
seconds. Open the site: the login page shows the three demo accounts and the
password, and `demo` / `reviewer` / `viewer` all work.

That same endpoint is what Vercel's cron calls daily at 08:00 UTC (03:00 or
04:00 Eastern) with `Authorization: Bearer $CRON_SECRET` (see `vercel.json`),
so the data is rebuilt every night. Admins also get a **Reset demo data now**
button in the banner. Running the curl again at any time gives a clean slate.

You never need to run the app on your laptop for this. If you prefer to work
against the Supabase database locally anyway (for example to debug), the same
code does it: `git pull`, `.venv/bin/pip install -r requirements.txt`, then set
`LIMS_DATABASE_URL`, `LIMS_DEMO_MODE=1` and `LIMS_DEMO_PASSWORD` in the shell
and run `.venv/bin/flask demo-reset` or `.venv/bin/flask run`. Without
`LIMS_DATABASE_URL` the laptop keeps using its local SQLite file as before.

Every push to `main` redeploys automatically. Pull requests get preview URLs
that share the same database, so treat them as the same demo.

## Optional: the Supabase integration on the Vercel marketplace

Instead of steps 1 and 2.2 you can add Supabase from **Vercel → Storage →
Supabase**. The integration creates the Supabase project and injects
`POSTGRES_URL`, `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` into the Vercel
project; the app reads those names as fallbacks, so only `LIMS_SECRET_KEY`,
`LIMS_DEMO_MODE`, `LIMS_DEMO_PASSWORD` and `CRON_SECRET` are left to add. Check
that `POSTGRES_URL` points at the pooler on port 6543; if it is the direct
IPv6 string, set `LIMS_DATABASE_URL` explicitly.

## What to know about this setup

* **It is public.** Anyone with the URL can log in with the demo accounts and
  see or change the fictional data. Do not enter real participant data. The
  nightly reset undoes everything.
* **Supabase free tier pauses a project after 7 days without activity.** The
  nightly cron keeps it awake. If it does pause, un-pause it in the dashboard.
* **Cold starts.** After a quiet spell the first page takes a second or two.
* **Uploads are capped at 4.5 MB** by Vercel; QC exports are far smaller.
* **Logs.** Vercel → project → **Logs** shows every request and traceback.
  Supabase → **Table Editor** shows the rows.
* **Local work is unchanged.** Without `LIMS_DATABASE_URL` the app uses SQLite
  as before; the test suite runs against SQLite, and against Postgres when
  `LIMS_TEST_DATABASE_URL` is set.
