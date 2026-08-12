from __future__ import annotations

import argparse
from datetime import timedelta

from app.database import SessionLocal
from app.media.voice_cleanup import cleanup_stale_voice_uploads


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expire abandoned Haroona voice-reaction uploads.",
    )
    parser.add_argument("--older-than-minutes", type=int, default=60)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    with SessionLocal() as db:
        result = cleanup_stale_voice_uploads(
            db,
            older_than=timedelta(minutes=args.older_than_minutes),
            limit=args.limit,
        )

    print(
        "Voice cleanup complete: "
        f"{result.expired} expired, "
        f"{result.objects_deleted} objects deleted, "
        f"{result.object_delete_failures} object cleanup failures."
    )


if __name__ == "__main__":
    main()
