from pathlib import Path
import argparse
from datetime import date
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_platform import create_app
from content_platform.services.reporting import (
    build_daily_publication_report,
    build_dashboard_report,
    send_daily_publication_report,
    send_dashboard_report,
)


def main():
    parser = argparse.ArgumentParser(description="Send or preview Supernova email reports.")
    parser.add_argument("--daily", action="store_true", help="Send the daily publication plan instead of the dashboard report.")
    parser.add_argument("--date", help="Report date for --daily, in YYYY-MM-DD format. Defaults to the app timezone date.")
    parser.add_argument("--dry-run", action="store_true", help="Print the report without sending email.")
    args = parser.parse_args()

    report_date = date.fromisoformat(args.date) if args.date else None
    app = create_app()
    with app.app_context():
        if args.dry_run:
            if args.daily:
                print(build_daily_publication_report(report_date))
            else:
                print(build_dashboard_report())
            return

        if args.daily:
            send_daily_publication_report(report_date)
            print("Daily publication report email sent.")
        else:
            send_dashboard_report()
            print("Dashboard report email sent.")


if __name__ == "__main__":
    main()
