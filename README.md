# Supernova

A Flask + Python platform for planning, adapting, scheduling, and publishing content across multiple social networks.

This project started as an academic scheduling project and evolved into an automation platform for real content operations: RSS intake, draft generation, platform-specific versions, media management, scheduling, recycling, logs, email reports, and API publishing.

## Elevator Pitch

Supernova helps a small team manage the full publication workflow:

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
- Real API publishing for Bluesky, Facebook feed/photo/video posts, and Instagram Graph feed media through the linked Facebook Page token
- Credential storage encrypted at rest
- API account verification for Facebook, Instagram, and Threads
- Long-lived Meta Page token helpers for Facebook; Instagram reuses the same Page token

## Platform Status

| Platform | Status |
| --- | --- |
| Bluesky | Real publishing implemented for text, links, hashtags, and image embeds. |
| Facebook | Real Page publishing implemented for feed posts, link posts, photos, and videos. Stories/Reels are protected until dedicated endpoints are implemented. |
| Instagram | Publishing implemented through the linked Facebook Page token for Graph API media containers. Feed media is the primary supported path; Reels/Stories remain endpoint-specific testing work. |
| Threads | OAuth connection, long-lived token exchange, credential verification, and publishing flow implemented. Needs final live publish validation with a real Threads token. |
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
EDITOR_USERNAME="squaredp"
EDITOR_PASSWORD="different-strong-password"
DATABASE_URL="postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres?sslmode=require"
APP_BASE_URL="https://your-render-service.onrender.com"
```

`ADMIN_USERNAME` can manage everything, including RSS feeds and API Accounts.
`EDITOR_USERNAME` can create, edit, schedule, and publish posts, but cannot open
RSS feed management or API credential pages. Use a different password for each
account.

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

Supabase may warn that public tables are accessible if Row-Level Security is not
enabled. Because Supernova uses a server-side Flask connection instead of a
browser Supabase client, direct `anon`/`authenticated` table access is not needed.
Run this file in Supabase SQL Editor after the tables exist:

```txt
docs/supabase_rls.sql
```

This enables RLS on the app tables and revokes direct public role access.

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

The repository includes a GitHub Actions workflow that runs hourly:

```txt
.github/workflows/rss-check.yml
```

It runs:

```bash
python3 scripts/check_rss_feeds.py
```

Recommended schedule:

```txt
0 * * * *
```

The scheduled workflow must use the same database as the web service, so `DATABASE_URL` must match the Render web service value.

Set these GitHub Actions repository secrets:

- `APP_BASE_URL`
- `DATABASE_URL`
- `SECRET_KEY`
- `CREDENTIALS_ENCRYPTION_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

`APP_BASE_URL` should be the public Render URL, for example:

```txt
https://your-render-service.onrender.com
```

When `APP_BASE_URL` is set, the RSS job first calls `/healthz` to wake/check the web service, then imports new RSS items as draft posts. It does not publish scheduled posts; publishing is handled by the separate scheduled publishing workflow below.

Render Cron Jobs can also run the same command if the account plan supports them. In that case, the cron service needs the same environment variables as the web service, especially `DATABASE_URL` and `APP_BASE_URL`.

## Scheduled Publishing Task

The repository also includes a GitHub Actions workflow that checks the publication queue every 5 minutes:

```txt
.github/workflows/publish-scheduled-posts.yml
```

It runs:

```bash
python3 scripts/process_publication_queue.py
```

Recommended schedule:

```txt
*/5 * * * *
```

GitHub Actions schedules are not a permanently running worker, so publication is processed in short polling intervals. Any post or recycled schedule with `scheduled_at` less than or equal to the app's current time is picked up on the next run, as long as it is inside the configured lookback window. In practice, a post scheduled for `14:00` should publish on the `14:00` or `14:05` run, depending on GitHub runner timing.

The workflow currently sets:

```txt
PUBLICATION_LOOKBACK_MINUTES=180
```

That gives the job a 3-hour catch-up window while avoiding accidental publication of very old scheduled posts.

Set these additional GitHub Actions repository secrets if scheduled publishing uses media uploads:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_MEDIA_BUCKET`

Optionally set:

- `APP_TIMEZONE=Europe/Lisbon`

Only schedule posts for platforms that have working credentials and implemented API publishing. Failures are marked in the app logs and affected posts/schedules are marked `Failed`.

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

## Meta Token Workflow

Graph API Explorer often gives short-lived user tokens. For daily team use, do not paste that user token directly as the publishing token. Facebook Page publishing and Instagram Graph publishing should use the Page token returned for the correct Facebook Page.

Facebook recommended workflow:

1. Save the Facebook Page ID, Meta App ID, and Meta App Secret in API Accounts.
2. Add the shared Meta OAuth callback shown in the Facebook card to the Meta app settings.
3. Click `Connect Facebook`.

The app opens Meta OAuth, receives the authorization code, exchanges it for a user token, fetches `/me/accounts`, selects the configured Page, stores the Page access token, and records the expiry information returned by Meta.

Instagram recommended workflow:

1. Connect Facebook first using the workflow above.
2. Save the Instagram Business/Creator ID in the Instagram card.
3. Save the linked Facebook Page ID in the Instagram card.
4. Click `Verify credentials` on Instagram.

Instagram publishing deliberately reuses the working Facebook Page token and the Meta Graph API. The Instagram card does not store a separate Instagram token, App ID, App Secret, or OAuth callback. This avoids stale Instagram Login tokens and keeps Meta publishing on one operational flow.

Production shared Meta callback URL for Facebook:

```txt
https://social-scheduler-u1we.onrender.com/settings/social-accounts/meta/callback
```

Add that exact URL, without a trailing slash, to the OAuth redirect URI allowlist for the Meta login product used by the app. In the Meta UI this is usually under `Facebook Login` / `Facebook Login for Business` settings as `Valid OAuth Redirect URIs`; the generic app authentication callback field in advanced settings is not enough by itself. The app domain should be `social-scheduler-u1we.onrender.com`.

Fallback workflow for Meta Page tokens:

1. Generate a short-lived user token in Graph API Explorer with:
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_posts`
2. Paste that temporary user token into the Facebook card.
3. Click `Generate long-lived Page token`.

Instagram then uses the saved Facebook Page token. Tokens can still be invalidated by Meta if permissions change, the app is removed, the password is reset, or Meta security policy requires reauthorization.

## Threads Token Workflow

Threads does not use the Facebook Page token and it does not accept Facebook/Graph Explorer tokens that start with `EAA`.

Threads recommended workflow:

1. Save the Threads App ID and Threads App Secret in the Threads card.
2. Add the Threads OAuth callback shown in the Threads card to the Threads API callback settings.
3. Click `Connect Threads`.
4. Log in with the Threads account that should publish content.
5. Click `Verify credentials`.

Production Threads callback URL:

```txt
https://social-scheduler-u1we.onrender.com/settings/social-accounts/threads/callback
```

The app receives the OAuth code, exchanges it for a Threads user token, upgrades it to a long-lived Threads token, saves the Threads User ID, and records token expiry metadata. If verification says `Cannot parse access token`, the saved token is not a Threads OAuth token; remove the Threads credentials, save the App ID/App Secret again, and reconnect.

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

- Finish dedicated Instagram Reels/Stories validation and format-specific guardrails
- Live-test Threads publishing after OAuth connection is accepted
- Add verification buttons for every API account
- Add retry/backoff queue for scheduled publishing
- Add analytics for best day/hour/platform
- Add AI-assisted copy, titles, and hashtags
- Add a dedicated demo mode for portfolio/recruiter walkthroughs
