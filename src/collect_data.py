
import json
import time
from pathlib import Path

import requests

BASE_URL = "https://www.moltbook.com/api/v1"
OUTPUT_DIR = Path("data/raw")
OUTPUT_FILE = OUTPUT_DIR / "posts.json"

def collect_posts(max_pages=3, page_size=25):
    session = requests.Session()
    posts_by_id = {}
    cursor = None

    for page in range(max_pages):
        params = {
            "sort": "new",
            "limit": page_size,
        }

        if cursor:
            params["cursor"] = cursor

        response = session.get(
            f"{BASE_URL}/posts",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        if not payload.get("success"):
            raise RuntimeError(
                f"Moltbook API returned an unsuccessful response: {payload}"
            )

        posts = payload.get("posts", [])

        for post in posts:
            post_id = post.get("id")
            if post_id:
                posts_by_id[post_id] = post

        print(
            f"Page {page + 1}: retrieved {len(posts)} posts; "
            f"{len(posts_by_id)} unique posts so far."
        )

        cursor = payload.get("next_cursor")

        if not payload.get("has_more") or not cursor:
            break

        time.sleep(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    records = list(posts_by_id.values())

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(records)} unique posts to {OUTPUT_FILE}")

if __name__ == "__main__":
    collect_posts(max_pages=20, page_size=25)

