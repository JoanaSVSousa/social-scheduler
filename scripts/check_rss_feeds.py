from pathlib import Path
import os
import sys
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.services.rss import check_all_feeds


def wake_web_service():
    base_url = os.environ.get("APP_BASE_URL", "").strip()
    if not base_url:
        return

    health_url = urljoin(base_url.rstrip("/") + "/", "healthz")
    request = Request(health_url, headers={"User-Agent": "ContentAutomationCron/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            print(f"Wake check: {health_url} returned HTTP {response.status}.")
    except (TimeoutError, URLError, OSError) as exc:
        print(f"Wake check warning: could not reach {health_url}: {exc}")


def main():
    app = create_app()
    with app.app_context():
        wake_web_service()
        result = check_all_feeds()
        print(
            f"RSS checked: {result['created']} draft(s) created, "
            f"{result['skipped']} item(s) skipped, {len(result['errors'])} error(s)."
        )
        for error in result["errors"]:
            print(f"ERROR: {error}")
        if result["errors"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
