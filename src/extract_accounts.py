
import json
from pathlib import Path

POSTS_FILE = Path("data/raw/posts.json")
OUTPUT_DIR = Path("data/raw")
OUTPUT_FILE = OUTPUT_DIR / "accounts.json"
REPORT_FILE = Path("data/processed/account_extraction_report.txt")


def extract_accounts():
    if not POSTS_FILE.exists():
        raise FileNotFoundError(
            f"Posts file not found: {POSTS_FILE}. "
            "Run src/collect_data.py first."
        )

    with POSTS_FILE.open("r", encoding="utf-8") as file:
        posts = json.load(file)

    if not isinstance(posts, list):
        raise ValueError("Expected posts.json to contain a list.")

    accounts = {}
    malformed_posts = 0
    missing_author_objects = 0
    missing_account_ids = 0
    author_id_fallbacks = 0

    for post in posts:
        if not isinstance(post, dict):
            malformed_posts += 1
            continue

        author = post.get("author")

        if not isinstance(author, dict):
            missing_author_objects += 1
            continue

        # Prefer the account ID embedded in the author object.
        account_id = author.get("id") or post.get("author_id")

        if account_id is None or not str(account_id).strip():
            missing_account_ids += 1
            continue

        account_id = str(account_id).strip()

        # Make sure every exported account has a consistent ID field.
        account = dict(author)
        account["id"] = account_id

        if not author.get("id") and post.get("author_id"):
            author_id_fallbacks += 1

        # One record per account ID.
        # Later appearances update the saved account details.
        accounts[account_id] = account

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            list(accounts.values()),
            file,
            ensure_ascii=False,
            indent=2,
        )

    report = [
        "Moltbook Account Extraction Report",
        "==================================",
        f"Posts in input file: {len(posts)}",
        f"Malformed post records: {malformed_posts}",
        f"Posts without usable author objects: {missing_author_objects}",
        f"Author objects without usable account IDs: {missing_account_ids}",
        f"Accounts identified using post author_id fallback: {author_id_fallbacks}",
        f"Unique accounts extracted: {len(accounts)}",
        f"Output file: {OUTPUT_FILE}",
        "",
        "Notes:",
        "- Accounts are extracted from author objects embedded in posts.",
        "- This does not represent every account on Moltbook.",
        "- Accounts without usable author objects cannot be recovered",
        "  by this script alone.",
    ]

    REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print("\n".join(report))


if __name__ == "__main__":
    extract_accounts()
