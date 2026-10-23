
import json
import time
from pathlib import Path

import requests

BASE_URL = "https://www.moltbook.com/api/v1"

POSTS_FILE = Path("data/raw/posts.json")
OUTPUT_DIR = Path("data/raw")
OUTPUT_FILE = OUTPUT_DIR / "comments.json"
PROGRESS_FILE = OUTPUT_DIR / "comments_progress.json"
REPORT_FILE = Path("data/processed/comment_collection_report.txt")

PAGE_SIZE = 25
REQUEST_DELAY = 1.1
MAX_RETRIES = 5


def load_json(path, default):
    """Load JSON or return a default if the file does not exist."""
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    """Write JSON through a temporary file to reduce corruption risk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    temp_path.replace(path)


def request_json(session, url, params):
    """Request one API page with retry and rate-limit handling."""
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(url, params=params, timeout=30)

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                try:
                    wait = float(retry_after)
                except (TypeError, ValueError):
                    wait = min(2 ** (attempt + 1), 60)

                print(f"Rate limited. Waiting {wait:g} seconds.")
                time.sleep(wait)
                continue

            response.raise_for_status()
            payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError("API response was not a JSON object.")

            return payload

        except (requests.RequestException, ValueError) as error:
            if attempt == MAX_RETRIES - 1:
                raise

            wait = min(2 ** (attempt + 1), 60)
            print(f"Request failed: {error}. Retrying in {wait}s.")
            time.sleep(wait)

    raise RuntimeError("Maximum request retries reached.")


def collect_comments():
    if not POSTS_FILE.exists():
        raise FileNotFoundError(
            f"Posts file not found: {POSTS_FILE}. "
            "Run src/collect_data.py first."
        )

    posts = load_json(POSTS_FILE, [])

    if not isinstance(posts, list):
        raise ValueError("Expected posts.json to contain a list.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Keep only valid post objects with IDs.
    valid_posts = [
        post for post in posts
        if isinstance(post, dict)
        and post.get("id") is not None
        and str(post.get("id")).strip()
    ]

    # Remove duplicate post IDs from the input list.
    posts_by_id = {
        str(post["id"]).strip(): post for post in valid_posts
    }

    comments = load_json(OUTPUT_FILE, [])
    if not isinstance(comments, list):
        raise ValueError("Expected comments.json to contain a list.")

    comments_by_id = {}
    missing_comment_ids = 0

    for comment in comments:
        if not isinstance(comment, dict):
            continue

        comment_id = comment.get("id")
        if comment_id is not None and str(comment_id).strip():
            comments_by_id[str(comment_id).strip()] = comment
        else:
            missing_comment_ids += 1

    progress = load_json(
        PROGRESS_FILE,
        {"completed_post_ids": [], "failed_post_ids": []},
    )

    completed_ids = set(progress.get("completed_post_ids", []))
    failed_ids = set(progress.get("failed_post_ids", []))

    # Revisit failed posts on a new run.
    failed_ids.intersection_update(posts_by_id.keys())
    completed_ids.intersection_update(posts_by_id.keys())

    # If a post was previously failed, retry it instead of skipping it.
    completed_ids.difference_update(failed_ids)

    total_posts = len(posts_by_id)
    newly_completed = 0
    posts_with_comments = 0
    posts_with_zero_comments = 0
    posts_failed_this_run = 0
    pages_fetched = 0
    comments_missing_ids_this_run = 0

    session = requests.Session()

    try:
        for index, (post_id, post) in enumerate(
            posts_by_id.items(), start=1
        ):
            if post_id in completed_ids:
                continue

            url = f"{BASE_URL}/posts/{post_id}/comments"
            cursor = None
            post_had_comments = False
            post_succeeded = True
            seen_cursors = set()

            try:
                while True:
                    params = {
                        "limit": PAGE_SIZE,
                        "sort": "new",
                    }

                    if cursor:
                        params["cursor"] = cursor

                    payload = request_json(session, url, params)

                    if not payload.get("success"):
                        raise RuntimeError(
                            f"API reported failure for post {post_id}."
                        )

                    page_comments = payload.get("comments", [])

                    if not isinstance(page_comments, list):
                        raise ValueError(
                            f"Invalid comments field for post {post_id}."
                        )

                    pages_fetched += 1

                    for comment in page_comments:
                        if not isinstance(comment, dict):
                            continue

                        comment_id = comment.get("id")

                        if comment_id is None or not str(comment_id).strip():
                            comments_missing_ids_this_run += 1
                            continue

                        comment_id = str(comment_id).strip()

                        # Keep one comment record per comment ID.
                        comments_by_id[comment_id] = comment
                        post_had_comments = True

                    if not payload.get("has_more"):
                        break

                    next_cursor = payload.get("next_cursor")

                    if not next_cursor or next_cursor in seen_cursors:
                        # Do not mark this post complete if pagination
                        # appears incomplete or stuck.
                        raise RuntimeError(
                            f"Pagination stopped unexpectedly for "
                            f"post {post_id}."
                        )

                    seen_cursors.add(next_cursor)
                    cursor = next_cursor
                    time.sleep(REQUEST_DELAY)

            except (requests.RequestException, ValueError, RuntimeError) as error:
                print(f"Failed post {post_id}: {error}")
                post_succeeded = False

            if post_succeeded:
                completed_ids.add(post_id)
                failed_ids.discard(post_id)
                newly_completed += 1

                if post_had_comments:
                    posts_with_comments += 1
                else:
                    posts_with_zero_comments += 1
            else:
                failed_ids.add(post_id)
                posts_failed_this_run += 1

            # Save data and progress after every post.
            save_json(OUTPUT_FILE, list(comments_by_id.values()))
            save_json(
                PROGRESS_FILE,
                {
                    "completed_post_ids": sorted(completed_ids),
                    "failed_post_ids": sorted(failed_ids),
                },
            )

            print(
                f"Post {index}/{total_posts} | "
                f"Completed: {len(completed_ids)}/{total_posts} | "
                f"Unique comments: {len(comments_by_id)} | "
                f"Failed this run: {posts_failed_this_run}"
            )

            time.sleep(REQUEST_DELAY)

    finally:
        session.close()

    report = [
        "Moltbook Comment Collection Report",
        "==================================",
        f"Unique input posts: {total_posts}",
        f"Posts completed across all runs: {len(completed_ids)}",
        f"Posts still failed/pending: {len(failed_ids)}",
        f"Posts completed in this run: {newly_completed}",
        f"Posts with comments in this run: {posts_with_comments}",
        f"Posts returning zero comments in this run: {posts_with_zero_comments}",
        f"Posts failed in this run: {posts_failed_this_run}",
        f"Comment pages fetched in this run: {pages_fetched}",
        f"Unique comments saved: {len(comments_by_id)}",
        f"Comments without IDs skipped this run: {comments_missing_ids_this_run}",
        f"Output file: {OUTPUT_FILE}",
        f"Progress file: {PROGRESS_FILE}",
        "",
        "Note: zero comments means the API returned no comments for a",
        "successfully completed post; it does not mean the request failed.",
        "Posts still marked failed should be retried and investigated.",
    ]

    REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print("\n" + "\n".join(report))


if __name__ == "__main__":
    collect_comments()
