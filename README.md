# Content Automation Platform

A Python platform for planning, scheduling, and tracking content publication across multiple channels.

This project is designed as an automation-focused academic project that can run locally with SQLite and in production with Supabase/Postgres.

## Features

- Dashboard with publication status counters
- Create, edit, delete, and list content posts
- Schedule posts by date, time, and platform
- Track status: Draft, Scheduled, Published, Failed
- Filter posts by platform, status, and search term
- Publication queue for posts that are due
- Logging for automation events
- Modular architecture prepared for future API publishers, retries, AI suggestions, and analytics
- Protected RSS intake that turns new feed items into draft posts
- Recycled posts with multiple schedule dates
- Grouped RSS article editor for adapting copy, formats, schedules, and media per social network
- RSS duplicate protection by source URL, useful when a general feed overlaps with category feeds

## Tech Stack

- Python
- Flask
- SQLite locally
- Supabase/Postgres in production
- HTML/CSS

Production is pinned to Python 3.12 through `.python-version`, `runtime.txt`, and `PYTHON_VERSION` in `render.yaml` for Render compatibility.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Then open:

```txt
http://127.0.0.1:5000
```

## Supabase/Postgres

The app uses SQLite when `DATABASE_URL` is not set. For Render + Supabase, set `DATABASE_URL` in Render using the Supabase Postgres connection string.

On Render, prefer the Supabase pooler connection string instead of the direct database host. The direct host can resolve to IPv6 and fail from Render with `Network is unreachable`.

Use a connection string shaped like:

```txt
postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres?sslmode=require
```

Do not commit the real value to GitHub.

## Protected RSS Area

RSS management is protected by an admin login.

For local development, the default credentials are:

```txt
Username: SquaredRedes
Password: change-me-local-admin
```

For real use, set these environment variables:

```bash
export ADMIN_PASSWORD="your-strong-password"
export ADMIN_USERNAME="SquaredRedes"
export SECRET_KEY="your-strong-secret-key"
```

Then open:

```txt
http://127.0.0.1:5000/rss
```

## Squared Potato RSS Feeds

Seed the Squared Potato feeds in the current database:

```bash
python3 scripts/seed_squared_feeds.py
```

Seed and immediately import new items as draft posts:

```bash
python3 scripts/seed_squared_feeds.py --check-now
```

Configured feeds:

- jogos: Facebook, Bluesky, X
- filmes: Facebook, Bluesky, X
- livros: Facebook, Bluesky, X
- tecnologia: Facebook, Bluesky, X

## Recurring RSS Task

On Render, create a Cron Job that runs every 2 hours:

```bash
python3 scripts/check_rss_feeds.py
```

It checks active RSS feeds, skips already imported items, and creates draft posts for the configured target platforms.

The in-app `Check feeds now` button runs a quick check only. Use the Render Cron Job for the regular full automation.

Recommended schedule:

```txt
0 */2 * * *
```

## RSS Media Workflow

RSS imports store the source article image URL when the feed exposes one through RSS media tags, image enclosures, or the article summary HTML.

In `Posts`, RSS articles are grouped into one row. Use `Edit versions` to adapt each network version on one page:

- choose the networks for that article;
- edit copy and format per platform;
- add recycling dates;
- upload images or videos per network version;
- use the source article image preview as a reference for media selection.

Current production note: uploaded media is stored in `static/uploads`. For serious team usage on Render, move this to persistent object storage such as Supabase Storage or S3.

## Email Dashboard Report

Send a dashboard-style email report with upcoming posts, recycled schedules, platform counts, and recent logs:

```bash
python3 scripts/send_dashboard_report.py
```

Preview the report without sending email:

```bash
python3 scripts/send_dashboard_report.py --dry-run
```

Required environment variables for email:

```bash
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USERNAME="your@email.com"
export SMTP_PASSWORD="your-password"
export SMTP_FROM_EMAIL="your@email.com"
export REPORT_TO_EMAIL="team@email.com"
```

## Demo Portfolio Data

To create a portfolio-friendly demo dataset:

```bash
python3 scripts/seed_demo.py
```

Use this for screenshots, curriculum demos, and recruiter walkthroughs. Keep real operational data separate.

## Project Structure

```txt
content_automation_platform/
├── app.py
├── requirements.txt
├── data/
│   └── scheduler.db
├── content_platform/
│   ├── __init__.py
│   ├── database.py
│   ├── models.py
│   ├── routes.py
│   └── services/
│       ├── analytics.py
│       ├── publisher.py
│       └── scheduler.py
├── static/
│   └── styles.css
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── logs.html
    ├── post_form.html
    └── posts.html
```

## Future Expansion

- Instagram, Facebook, LinkedIn, X, Threads, Bluesky, TikTok, and YouTube API integrations
- Retry system for failed publications
- AI-generated titles, captions, and hashtags
- Dashboard monthly calendar view
- Inline calendar editing with a compact pop-up editor
- Drag-and-drop calendar rescheduling for post schedules
- Analytics for best day, best hour, and platform frequency
- One-click option to attach the source article image directly to selected post versions
- Persistent media storage through Supabase Storage or S3
