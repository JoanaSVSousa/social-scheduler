from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.services.rss import check_all_feeds


app = create_app()

with app.app_context():
    result = check_all_feeds()
    print(
        f"RSS checked: {result['created']} draft(s) created, "
        f"{result['skipped']} item(s) skipped, {len(result['errors'])} error(s)."
    )
    for error in result["errors"]:
        print(f"ERROR: {error}")
    if result["errors"]:
        raise SystemExit(1)
