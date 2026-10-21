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
4. The project URL is `https://<ref>.supabase.co`, where `<ref>` is the
   20-letter project reference that appears in your browser's address bar
   (`supabase.com/dashboard/project/<ref>`) and in the pooler string after
   `postgres.`. The dashboard also shows it in **Connect → App Frameworks** and
   in **Project Settings → Data API**. This is `LIMS_SUPABASE_URL`.
5. **Project Settings → API Keys** (the gear icon in the left sidebar; the page
   used to be called "API"). Open the **Legacy anon, service_role** tab and
   copy the **service_role** key (click Reveal; it starts with `eyJ`). This is
   `LIMS_SUPABASE_SERVICE_KEY`. Use the legacy key rather than a new
   `sb_secret_...` key: it is what the app's storage client was written and
   tested against. The service key bypasses row security; it is used only
   server-side and must never be put in a browser or the repo.

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
   | `LIMS_SUPABASE_SERVICE_KEY` | the service_role key from step 1.5 |
   | `LIMS_SECRET_KEY` | output of `python3 -c 'import secrets;print(secrets.token_hex(32))'` |
   | `LIMS_DEMO_MODE` | `1` |
   | `LIMS_DEMO_PASSWORD` | the password for the three demo accounts; share it with testers yourself, the site never displays it |
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
seconds (that count is the main participant; three smaller ones are created too). Open the site: the login page names the three demo accounts (the
password is not shown), and `demo` / `reviewer` / `viewer` all work with
`LIMS_DEMO_PASSWORD`. Send testers the URL and the password separately.

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

## Supabase's "RLS Disabled in Public" security advisor

Supabase exposes every table in the `public` schema through its own REST API
(PostgREST) to anyone who holds the project's anon key, and its security
advisor flags tables that have no row level security. This app never uses
that API: it connects to Postgres directly as the table owner. So the schema
setup turns row level security on for every table with no policies (which
makes the REST API return nothing) and revokes the REST roles' grants on the
tables as well. The advisor is satisfied the next time the schema is built,
which is the next demo reset (nightly, or the curl in step 3).

If you want it clean right now, or want to check, paste this into
**SQL Editor** in the Supabase dashboard and run it:

```sql
do $$ declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;
revoke all on all tables in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
```

Then **Advisors → Security** → Refresh. The app keeps working because the
`postgres` role it connects as owns the tables and is not subject to RLS.

## What to know about this setup

* **It is public.** Anyone with the URL and the demo password can log in and
  see or change the fictional data. The password is not shown on the site,
  but it is shared, so change `LIMS_DEMO_PASSWORD` in Vercel and run the
  reset if it gets out. Do not enter real participant data. The
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
