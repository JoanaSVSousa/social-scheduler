# Content Automation Platform

A Flask + Python platform for planning, adapting, scheduling, and publishing content across multiple social networks.

This project started as an academic scheduling project and evolved into an automation platform for real content operations: RSS intake, draft generation, platform-specific versions, media management, scheduling, recycling, logs, email reports, and API publishing.

## Elevator Pitch

Content Automation Platform helps a small team manage the full publication workflow:

```txt
RSS/article discovery
-> draft generation
-> network-specific copy and format
-> media upload/optimization
-> scheduling/recycling
-> queue processing
-> API publishing
-> logs and reporting
```

The goal is not just to store posts. The goal is to model a real automation workflow with state, validation, repeatable jobs, and clear operational feedback.

## Current Capabilities

- Login-protected web app
- Dashboard with status counters, platform counts, upcoming queue, and monthly calendar
- Post library with filters, sorting, grouped RSS articles, and publish-now actions
- Manual posts and RSS-generated draft posts
- Platform-specific versions for the same RSS article
- General defaults with per-network overrides
- Scheduling and recycled publication dates
- Drag-and-drop calendar rescheduling
- Logs for publication, RSS, API, and operational events
- Email dashboard report script
- SQLite for local development
- Supabase/Postgres support for production
- Supabase Storage support for public media URLs
- Image compression for API limits
- MP4 video upload validation for API publishing
- Real API publishing for Bluesky and Facebook feed/photo/video posts
- Credential storage encrypted at rest
- API account verification for Meta/Facebook and Instagram credentials

## Platform Status

| Platform | Status |
| --- | --- |
| Bluesky | Real publishing implemented for text, links, hashtags, and image embeds. |
| Facebook | Real Page publishing implemented for feed posts, link posts, photos, and videos. Stories/Reels are protected until dedicated endpoints are implemented. |
| Instagram | Credential storage and publishing flow scaffolded. Needs final credential verification/testing for real use. |
| Threads | Credential storage and publishing flow scaffolded. Needs correct user token flow and final testing. |
| X | Kept in roadmap/manual flow because free general API access is deprecated. |
| LinkedIn | Credential storage and text/link publishing scaffolded. |
| TikTok | Credential storage scaffolded; upload flow is roadmap. |
| YouTube Shorts | Credential storage scaffolded; resumable video upload is roadmap. |

## Tech Stack

- Python 3.12
- Flask
- SQLite locally
- Supabase/Postgres in production
- Supabase Storage for public media assets
- HTML, Jinja templates, CSS, and vanilla JavaScript
- Pillow for image optimization
- imageio-ffmpeg/ffmpeg scaffold for future background video conversion
- Gunicorn on Render

Production is pinned to Python 3.12 through `.python-version`, `runtime.txt`, and `PYTHON_VERSION` in `render.yaml`.

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

## Environment Variables

Use `.env.example` as a template. Never commit real secrets.

Required for production:

```bash
SECRET_KEY="long-random-secret"
CREDENTIALS_ENCRYPTION_KEY="generated-fernet-key"
ADMIN_USERNAME="SquaredRedes"
ADMIN_PASSWORD="strong-password"
DATABASE_URL="postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres?sslmode=require"
```

For public media uploads:

```bash
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="server-only-service-role-key"
SUPABASE_MEDIA_BUCKET="social-media"
```

Optional future video-processing fallback:

```bash
FFMPEG_BINARY="/usr/bin/ffmpeg"
```

## Supabase/Postgres

The app uses SQLite when `DATABASE_URL` is not set. For Render + Supabase, set `DATABASE_URL` in Render.

On Render, prefer the Supabase pooler connection string instead of the direct database host:

```txt
postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres?sslmode=require
```

Do not commit the real value to GitHub.

## RSS Workflow

RSS management is protected by login.

Seed the Squared Potato feeds:

```bash
python3 scripts/seed_squared_feeds.py
```

Seed and immediately import new items as drafts:

```bash
python3 scripts/seed_squared_feeds.py --check-now
```

Configured Squared Potato feeds:

- jogos: Facebook, Bluesky, X
- filmes: Facebook, Bluesky, X
- livros: Facebook, Bluesky, X
- tecnologia: Facebook, Bluesky, X

RSS duplicate protection uses the source URL, so a future general feed should not duplicate articles already imported from category feeds.

## Recurring RSS Task

On Render, create a Cron Job that runs every 2 hours:

```bash
python3 scripts/check_rss_feeds.py
```

Recommended schedule:

```txt
0 */2 * * *
```

The Cron Job must use the same environment variables as the web service, especially `DATABASE_URL`.

## Media Workflow

Accepted upload formats:

- PNG
- JPG/JPEG
- GIF
- WEBP
- MP4

Images are optimized before API upload when needed.

Videos are currently accepted as MP4 and are not transcoded during the web request. This keeps Render workers responsive while still allowing Facebook/Meta video publishing through public Supabase Storage URLs. Heavier MOV/WEBM conversion should run later as a background job, not inside the save/publish button.

For Meta APIs, uploaded media must have a public URL. In production, this is handled through Supabase Storage.

## Email Dashboard Report

Send a dashboard-style email report:

```bash
python3 scripts/send_dashboard_report.py
```

Preview without sending:

```bash
python3 scripts/send_dashboard_report.py --dry-run
```

Required SMTP variables:

```bash
SMTP_HOST="smtp.example.com"
SMTP_PORT="587"
SMTP_USERNAME="your@email.com"
SMTP_PASSWORD="your-password"
SMTP_FROM_EMAIL="your@email.com"
REPORT_TO_EMAIL="team@email.com"
```

## Project Structure

```txt
content_platform/
├── auth.py
├── database.py
├── models.py
├── routes.py
├── security.py
└── services/
    ├── analytics.py
    ├── media.py
    ├── media_optimizer.py
    ├── platform_publishers.py
    ├── publisher.py
    ├── reporting.py
    ├── rss.py
    ├── rss_groups.py
    ├── scheduler.py
    ├── schedules.py
    └── social_accounts.py
```

## Recruiter Summary

This project demonstrates:

- Python backend development
- Flask web application design
- SQL data modeling
- CRUD workflows
- RSS automation
- job scheduling
- state management
- API integrations
- encrypted credential storage
- file upload validation
- media optimization
- security hardening
- deployment planning with Render and Supabase

## Roadmap

- Finish Instagram publishing with feed, reels, stories, and video validation
- Finish Threads OAuth/user-token flow
- Add verification buttons for every API account
- Add retry/backoff queue for scheduled publishing
- Add analytics for best day/hour/platform
- Add AI-assisted copy, titles, and hashtags
- Add a dedicated demo mode for portfolio/recruiter walkthroughs
