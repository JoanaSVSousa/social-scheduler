from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.database import get_connection
from content_platform.models import Post
from content_platform.services.rss import create_feed
from content_platform.services.scheduler import create_post
from content_platform.services.schedules import replace_schedules


DEMO_POSTS = [
    Post(
        title="Instagram Reel - Automation tip",
        content="Short vertical video explaining one practical automation workflow.",
        hashtags="#automation #python #content",
        platform="Instagram",
        content_format="Reel",
        scheduled_at="2026-06-25T18:00",
        status="Scheduled",
    ),
    Post(
        title="X thread - RSS to drafts",
        content="A short thread explaining how RSS items become draft posts for review.",
        hashtags="#automation #x #workflow",
        platform="X",
        content_format="Thread",
        scheduled_at="",
        status="Draft",
    ),
    Post(
        title="Bluesky image post - platform update",
        content="A lightweight update designed for a text-first audience.",
        hashtags="#bluesky #contentops",
        platform="Bluesky",
        content_format="Image Post",
        scheduled_at="2026-06-27T11:30",
        status="Scheduled",
    ),
    Post(
        title="LinkedIn product note",
        content="Professional summary of the Supernova architecture.",
        hashtags="#python #flask #automation",
        platform="LinkedIn",
        content_format="Text Post",
        scheduled_at="",
        status="Published",
    ),
]


app = create_app()

with app.app_context():
    with get_connection() as conn:
        conn.execute("DELETE FROM rss_feeds WHERE name LIKE 'Demo %'")
        conn.execute("DELETE FROM posts WHERE title IN ({})".format(",".join("?" for _ in DEMO_POSTS)), [post.title for post in DEMO_POSTS])

    for post in DEMO_POSTS:
        post_id = create_post(post)
        if post.title == "Instagram Reel - Automation tip":
            replace_schedules(post_id, ["2026-06-25T18:00", "2026-06-30T18:00", "2026-07-05T18:00"])

    create_feed(
        "Demo Tech News",
        "https://example.com/demo-tech-feed.xml",
        ["X", "Bluesky", "LinkedIn"],
        "#tech #automation",
    )
    print("Demo data seeded.")
