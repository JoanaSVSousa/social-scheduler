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

## Tech Stack

- Python
- Flask
- SQLite locally
- Supabase/Postgres in production
- HTML/CSS

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

Use a connection string shaped like:

```txt
postgresql://USER:PASSWORD@HOST:PORT/DATABASE?sslmode=require
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

## Hourly RSS Task

On PythonAnywhere, schedule this script to run hourly:

```bash
python3 scripts/check_rss_feeds.py
```

It checks active RSS feeds, skips already imported items, and creates draft posts for the configured target platforms.

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
- Calendar view
- Analytics for best day, best hour, and platform frequency
