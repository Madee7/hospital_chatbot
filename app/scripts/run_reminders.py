"""
Process due appointment reminders.

Usage:
  python -m app.scripts.run_reminders
  python -m app.scripts.run_reminders --dry-run
  python -m app.scripts.run_reminders --force   # demo: send all pending even if not due
  python -m app.scripts.run_reminders --loop --interval 60
"""

from __future__ import annotations

import argparse
import time

from app.db.database import SessionLocal
from app.services.reminder_service import process_due_reminders


def main() -> None:
    parser = argparse.ArgumentParser(description="Send due WhatsApp appointment reminders")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process all pending reminders (ignore scheduled_at) for demo",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between loops")
    args = parser.parse_args()

    while True:
        db = SessionLocal()
        try:
            result = process_due_reminders(
                db,
                dry_run=args.dry_run,
                force_all_pending=args.force,
                limit=args.limit,
            )
            print(
                f"reminders processed={result['processed']} "
                f"sent={result['sent']} failed={result['failed']} "
                f"skipped={result['skipped']} dry_run={result['dry_run']}"
            )
            for row in result["details"]:
                print(f"  - {row}")
        finally:
            db.close()

        if not args.loop:
            break
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
