# Deployment Options

## Option A: PythonAnywhere

Best when you want the simplest path from local Flask + SQLite to online.

Good fit for:

- Flask app;
- SQLite;
- scheduled tasks;
- hourly RSS checks;
- email report scripts;
- small private team usage.

Tradeoff:

- less flexible than a full cloud setup;
- scaling and team workflows are more limited.

Recommended if the priority is to start using the tool quickly.

## Option B: Render + Supabase

Best when you want a more production-like setup for a small team.

Good fit for:

- hosted Flask app on Render;
- Postgres database on Supabase;
- team access;
- future API integrations;
- persistent online usage.

Tradeoff:

- requires migrating the database layer from SQLite to Postgres-compatible SQL;
- uploads need object storage or another persistent file strategy;
- more setup work.

Recommended if the priority is collaboration and long-term use.

Current project status:

- Render web service files are prepared: `render.yaml` and `Procfile`.
- Secrets must be configured in Render environment variables, not committed to GitHub.
- Supabase/Postgres is the recommended production database, but the current code still uses SQLite.
- Before using Supabase in production, migrate the database layer from SQLite placeholders to Postgres-compatible queries and move uploads to persistent object storage.

Safe GitHub checklist:

- Commit `.env.example`, never a real `.env`.
- Do not commit `data/scheduler.db`.
- Do not commit `static/uploads/`.
- Store passwords, SMTP credentials, and database URLs only as deployment environment variables.

## Suggested Path

1. Use SQLite locally while polishing the product.
2. Create the demo version for portfolio/recruiters.
3. Deploy first private version on PythonAnywhere if speed matters.
4. Move to Render + Supabase when the team really starts depending on it.

## Deployment Readiness Checklist

- Set `ADMIN_PASSWORD`.
- Set `ADMIN_USERNAME`.
- Set `SECRET_KEY`.
- Disable Flask debug mode.
- Configure SMTP env vars.
- Configure hourly RSS script.
- Configure daily/weekly email report script.
- Decide where uploads should live.
- Decide whether SQLite is enough or Postgres is needed.
