from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.services.rss import check_all_feeds, create_feed, list_feeds
from content_platform.services.squared_feeds import SQUARED_FEEDS


def seed_squared_feeds(check_now=False):
    existing_urls = {feed["url"] for feed in list_feeds()}
    created = 0
    skipped = 0

    for feed in SQUARED_FEEDS:
        if feed["url"] in existing_urls:
            skipped += 1
            continue
        if create_feed(feed["name"], feed["url"], feed["platforms"], feed["hashtags"]):
            created += 1
        else:
            skipped += 1

    print(f"Squared feeds seeded: {created} created, {skipped} already present.")

    if check_now:
        result = check_all_feeds()
        print(
            f"RSS checked: {result['created']} draft(s) created, "
            f"{result['skipped']} item(s) skipped, {len(result['errors'])} error(s)."
        )
        for error in result["errors"]:
            print(f"ERROR: {error}")


def main():
    parser = argparse.ArgumentParser(description="Seed the Squared Potato RSS feeds.")
    parser.add_argument("--check-now", action="store_true", help="Import new RSS items immediately after seeding.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        seed_squared_feeds(check_now=args.check_now)


if __name__ == "__main__":
    main()
