
import json
import time
from pathlib import Path

import requests

BASE_URL = "https://www.moltbook.com/api/v1"
POSTS_FILE = Path("data/raw/posts.json")
OUTPUT_FILE = Path("data/raw/comments.json")


def collect_comments():
    with POSTS_FILE.open("r", encoding="utf-8") as file:
        posts = json.load(file)

    session = requests.Session()
    comments_by_id = {}

    for index, post in enumerate(posts, start=1):
        post_id = post.get("id")

        if not post_id:
            continue

        url = f"{BASE_URL}/posts/{post_id}/comments"
        cursor = None

        try:
            while True:
                params = {"limit": 25, "sort": "new"}

                if cursor:
                    params["cursor"] = cursor

                response = session.get(
                    url,
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                payload = response.json()

                if not payload.get("success"):
                    print(f"API returned unsuccessful response for {post_id}")
                    break

                comments = payload.get("comments", [])

                for comment in comments:
                    comment_id = comment.get("id")

                    if comment_id:
                        comments_by_id[comment_id] = comment

                if not payload.get("has_more"):
                    break

                next_cursor = payload.get("next_cursor")

                if not next_cursor or next_cursor == cursor:
                    break

                cursor = next_cursor
                time.sleep(0.5)

        except requests.RequestException as error:
            print(f"Failed to collect comments for {post_id}: {error}")

        print(
            f"Processed post {index}/{len(posts)}; "
            f"{len(comments_by_id)} unique comments collected"
        )

        time.sleep(0.5)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            list(comments_by_id.values()),
            file,
            ensure_ascii=False,
            indent=2
        )

    print(f"\nPosts examined: {len(posts)}")
    print(f"Unique comments collected: {len(comments_by_id)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    collect_comments()
