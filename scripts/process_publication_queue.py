from pathlib import Path
import os
import sys
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.services.clock import app_now_string
from content_platform.services.publisher import process_publication_queue


def wake_web_service():
    base_url = os.environ.get("APP_BASE_URL", "").strip()
    if not base_url:
        return

    health_url = urljoin(base_url.rstrip("/") + "/", "healthz")
    request = Request(health_url, headers={"User-Agent": "ContentAutomationPublisher/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            print(f"Wake check: {health_url} returned HTTP {response.status}.")
    except (TimeoutError, URLError, OSError) as exc:
        print(f"Wake check warning: could not reach {health_url}: {exc}")


def main():
    app = create_app()
    with app.app_context():
        wake_web_service()
        lookback = os.environ.get("PUBLICATION_LOOKBACK_MINUTES", "1440")
        print(f"Publication queue time: {app_now_string()}. Catch-up window: {lookback} minute(s).")
        published = process_publication_queue()
        print(f"Publication queue checked: {published} item(s) published.")


if __name__ == "__main__":
    main()
