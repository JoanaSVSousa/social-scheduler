from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.services.reporting import build_dashboard_report, send_dashboard_report


app = create_app()

with app.app_context():
    if "--dry-run" in sys.argv:
        print(build_dashboard_report())
    else:
        send_dashboard_report()
        print("Dashboard report email sent.")
