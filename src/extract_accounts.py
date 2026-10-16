
import json
from pathlib import Path

POSTS_FILE = Path("data/raw/posts.json")
OUTPUT_FILE = Path("data/raw/accounts.json")


def extract_accounts():
    with POSTS_FILE.open("r", encoding="utf-8") as file:
        posts = json.load(file)

    accounts = {}

    for post in posts:
        author = post.get("author")

        if not isinstance(author, dict):
            continue

        account_id = author.get("id") or post.get("author_id")

        if not account_id:
            continue

        # Keep one record per account ID.
        accounts[account_id] = author

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            list(accounts.values()),
            file,
            ensure_ascii=False,
            indent=2
        )

    print(f"Posts examined: {len(posts)}")
    print(f"Unique accounts extracted: {len(accounts)}")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    extract_accounts()
