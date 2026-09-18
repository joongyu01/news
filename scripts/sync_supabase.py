"""Backfill committed drafts without sending notifications or overwriting reviews."""
from .config import DRAFT_DIR
from .digest import Digest
from . import storage


def main():
    if not storage.enabled():
        raise RuntimeError("Supabase settings are required")
    for path in sorted(DRAFT_DIR.glob("*.json")):
        digest = Digest.load(path)
        if storage.read("news_drafts", digest.date) is None:
            storage.save_draft(digest)
            print(f"Uploaded draft: {digest.date}")


if __name__ == "__main__":
    main()
