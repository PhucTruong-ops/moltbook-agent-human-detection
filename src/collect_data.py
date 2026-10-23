
import json
import time
from pathlib import Path

import requests

BASE_URL = "https://www.moltbook.com/api/v1"
OUTPUT_DIR = Path("data/raw")
OUTPUT_FILE = OUTPUT_DIR / "posts.json"
TEMP_FILE = OUTPUT_DIR / "posts.tmp.json"

TARGET_TOTAL = 20_000
PAGE_SIZE = 25
REQUEST_DELAY = 1.1
MAX_RETRIES = 5


def save_posts(posts_by_id):
    """Save collected posts safely, including progress after each page."""
    records = list(posts_by_id.values())

    with TEMP_FILE.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    # Replace the previous file only after the new file is complete.
    TEMP_FILE.replace(OUTPUT_FILE)


def collect_posts(target_total=TARGET_TOTAL, page_size=PAGE_SIZE):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load the existing dataset so a rerun can resume from saved records.
    posts_by_id = {}

    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open("r", encoding="utf-8") as file:
            existing_posts = json.load(file)

        for post in existing_posts:
            post_id = post.get("id")
            if post_id:
                posts_by_id[post_id] = post

        print(f"Loaded {len(posts_by_id)} existing unique posts.")

    session = requests.Session()
    cursor = None
    pages_fetched = 0

    try:
        while len(posts_by_id) < target_total:
            params = {
                "sort": "new",
                "limit": page_size,
            }

            if cursor:
                params["cursor"] = cursor

            # Retry temporary network errors, server errors, and rate limits.
            for attempt in range(MAX_RETRIES):
                try:
                    response = session.get(
                        f"{BASE_URL}/posts",
                        params=params,
                        timeout=30,
                    )

                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            wait_seconds = float(retry_after)
                        except (TypeError, ValueError):
                            wait_seconds = min(2 ** (attempt + 1), 60)

                        print(
                            f"Rate limited. Waiting {wait_seconds:g} seconds."
                        )
                        time.sleep(wait_seconds)
                        continue

                    response.raise_for_status()
                    payload = response.json()
                    break

                except (requests.RequestException, ValueError) as error:
                    if attempt == MAX_RETRIES - 1:
                        raise

                    wait_seconds = min(2 ** (attempt + 1), 60)
                    print(f"Request failed: {error}")
                    print(f"Retrying in {wait_seconds} seconds...")
                    time.sleep(wait_seconds)

            else:
                raise RuntimeError("Maximum retries reached.")

            if not payload.get("success"):
                raise RuntimeError(
                    f"Moltbook API returned an unsuccessful response: "
                    f"{payload}"
                )

            posts = payload.get("posts", [])
            pages_fetched += 1
            new_ids = 0

            for post in posts:
                post_id = post.get("id")
                if post_id and post_id not in posts_by_id:
                    posts_by_id[post_id] = post
                    new_ids += 1
                elif post_id:
                    # Refresh the existing record with the latest API version.
                    posts_by_id[post_id] = post

            # Checkpoint progress so a later run can recover this data.
            save_posts(posts_by_id)

            print(
                f"Page {pages_fetched}: received {len(posts)} posts; "
                f"{new_ids} new unique IDs; "
                f"{len(posts_by_id)} unique posts saved."
            )

            cursor = payload.get("next_cursor")

            if len(posts_by_id) >= target_total:
                break

            if not payload.get("has_more") or not cursor:
                print("API reports no more pages.")
                break

            time.sleep(REQUEST_DELAY)

    finally:
        session.close()

    print(f"\nCollection finished.")
    print(f"Unique posts saved: {len(posts_by_id)}")
    print(f"Target: {target_total}")
    print(f"File: {OUTPUT_FILE}")


if __name__ == "__main__":
    collect_posts()
