"""
Refresh the legacy Moltbook database from data/raw JSON files.

Target database: moltbook_research
This script intentionally does NOT write to moltbook_research_new.

Safety features:
- Loads and validates all JSON files before touching the database.
- Checks primary IDs and foreign-key-like relationships in the raw data.
- Uses Connector/Python's pure-Python implementation (use_pure=True).
- Requires explicit confirmation before deleting existing rows.
- Uses one transaction; failures trigger rollback.
- Inserts parent comments before nested replies.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"

load_dotenv(PROJECT_ROOT / ".env")

EXPECTED_DB_NAME = "moltbook_research"
BATCH_SIZE = 500


# ============================================================
# GENERAL HELPERS
# ============================================================

def as_text(value):
    """Convert an ID to a consistent string, preserving None."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def get_dict(value):
    """Return a dictionary or an empty dictionary."""
    return value if isinstance(value, dict) else {}


def get_account_id(record):
    """Read an author ID from a direct field or nested author object."""
    author = get_dict(record.get("author"))
    return as_text(record.get("author_id") or author.get("id"))


def parse_datetime(value):
    """Convert an ISO timestamp to a UTC, timezone-naive MySQL datetime."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return None


def json_for_mysql(record):
    """Serialize a JSON-compatible record for a MySQL JSON column."""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def load_json(filename):
    """Load a JSON list from data/raw."""
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    print(f"Loading {filename}...")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"{filename} must contain a JSON list.")

    if not all(isinstance(item, dict) for item in data):
        raise ValueError(f"{filename} contains records that are not JSON objects.")

    print(f"Loaded {len(data):,} records from {filename}")
    return data


# ============================================================
# FLATTEN AND VALIDATE COMMENTS
# ============================================================

def flatten_comments(top_level_comments):
    """
    Flatten nested comments into preorder records.

    The parent is placed before its replies. For nested replies, the
    structural parent ID is used. A reply inherits its parent's post_id
    if it does not contain its own post_id.
    """
    flattened = []

    def visit(comment_list, parent_id=None, inherited_post_id=None, depth=0):
        for comment in comment_list:
            if not isinstance(comment, dict):
                raise ValueError("A comment/reply is not a JSON object.")

            comment_id = as_text(comment.get("id"))
            if not comment_id:
                raise ValueError("A comment/reply is missing its id.")

            post_id = as_text(comment.get("post_id")) or inherited_post_id
            if not post_id:
                raise ValueError(
                    f"Comment {comment_id} has no post_id, and no parent post_id "
                    "is available to inherit."
                )

            explicit_parent_id = as_text(
                comment.get("parent_comment_id") or comment.get("parent_id")
            )
            actual_parent_id = parent_id if parent_id is not None else explicit_parent_id

            replies = comment.get("replies", [])
            if replies is None:
                replies = []
            if not isinstance(replies, list):
                raise ValueError(
                    f"Comment {comment_id} has a 'replies' value that is not a list."
                )

            raw_record = dict(comment)
            raw_record.pop("replies", None)

            flattened.append({
                "comment_id": comment_id,
                "post_id": post_id,
                "author_id": get_account_id(comment),
                "parent_comment_id": actual_parent_id,
                "content": comment.get("content"),
                "created_at": parse_datetime(
                    comment.get("created_at") or comment.get("createdAt")
                ),
                "updated_at": parse_datetime(
                    comment.get("updated_at") or comment.get("updatedAt")
                ),
                "reply_count": comment.get(
                    "reply_count", comment.get("replyCount")
                ),
                "depth": comment.get("depth", depth),
                "is_deleted": comment.get("is_deleted"),
                "is_spam": comment.get("is_spam"),
                "raw_json": json_for_mysql(raw_record),
            })

            visit(
                replies,
                parent_id=comment_id,
                inherited_post_id=post_id,
                depth=depth + 1,
            )

    visit(top_level_comments)
    return flattened


def validate_raw_data(accounts, posts, comments):
    """Validate IDs and relationships before connecting to MySQL."""
    print("\nVALIDATING RAW DATA")

    account_ids = [as_text(item.get("id")) for item in accounts]
    post_ids = [as_text(item.get("id")) for item in posts]

    if any(value is None for value in account_ids):
        raise ValueError("At least one account is missing its id.")
    if any(value is None for value in post_ids):
        raise ValueError("At least one post is missing its id.")

    account_id_set = set(account_ids)
    post_id_set = set(post_ids)

    if len(account_id_set) != len(account_ids):
        raise ValueError("Duplicate account IDs were found in accounts.json.")
    if len(post_id_set) != len(post_ids):
        raise ValueError("Duplicate post IDs were found in posts.json.")

    # Validate post authors against accounts.
    missing_post_authors = sorted({
        get_account_id(post)
        for post in posts
        if get_account_id(post) and get_account_id(post) not in account_id_set
    })
    posts_without_author = [
        as_text(post.get("id"))
        for post in posts
        if not get_account_id(post)
    ]

    if posts_without_author:
        raise ValueError(
            f"{len(posts_without_author):,} posts have no author ID. "
            f"Examples: {posts_without_author[:5]}"
        )
    if missing_post_authors:
        raise ValueError(
            f"{len(missing_post_authors):,} post author IDs are absent from "
            f"accounts.json. Examples: {missing_post_authors[:5]}"
        )

    flat_comments = flatten_comments(comments)

    comment_ids = [item["comment_id"] for item in flat_comments]
    comment_id_set = set(comment_ids)

    if len(comment_id_set) != len(comment_ids):
        raise ValueError("Duplicate comment IDs were found across the comment tree.")

    missing_comment_authors = sorted({
        item["author_id"]
        for item in flat_comments
        if item["author_id"] and item["author_id"] not in account_id_set
    })
    comments_without_author = [
        item["comment_id"] for item in flat_comments if not item["author_id"]
    ]

    if comments_without_author:
        raise ValueError(
            f"{len(comments_without_author):,} comments have no author ID. "
            f"Examples: {comments_without_author[:5]}"
        )
    if missing_comment_authors:
        raise ValueError(
            f"{len(missing_comment_authors):,} comment author IDs are absent "
            f"from accounts.json. Examples: {missing_comment_authors[:5]}"
        )

    missing_comment_posts = sorted({
        item["post_id"]
        for item in flat_comments
        if item["post_id"] not in post_id_set
    })
    if missing_comment_posts:
        raise ValueError(
            f"{len(missing_comment_posts):,} comment post IDs are absent from "
            f"posts.json. Examples: {missing_comment_posts[:5]}"
        )

    missing_parents = sorted({
        item["parent_comment_id"]
        for item in flat_comments
        if item["parent_comment_id"]
        and item["parent_comment_id"] not in comment_id_set
    })
    if missing_parents:
        raise ValueError(
            f"{len(missing_parents):,} parent comment IDs are absent from the "
            f"collected comment set. Examples: {missing_parents[:5]}"
        )

    print(f"Accounts: {len(accounts):,} unique IDs")
    print(f"Posts: {len(posts):,} unique IDs")
    print(f"Top-level comments: {len(comments):,}")
    print(f"Comments and nested replies: {len(flat_comments):,}")
    print("Post author references: valid")
    print("Comment author references: valid")
    print("Comment-to-post references: valid")
    print("Parent-comment references: valid")

    return flat_comments


# ============================================================
# DATABASE CONNECTION
# ============================================================

def connect_db():
    """Connect only to the legacy database using the pure Python connector."""
    required = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Missing database settings in .env: " + ", ".join(missing)
        )

    database_name = os.getenv("DB_NAME")
    if database_name != EXPECTED_DB_NAME:
        raise RuntimeError(
            f"Wrong database selected: {database_name}. "
            f"This script only refreshes {EXPECTED_DB_NAME}."
        )

    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=database_name,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        use_pure=True,
        autocommit=False,
    )

    print(f"\nConnected to database: {database_name}")
    print("Connector mode: pure Python")
    return connection


def ensure_no_foreign_keys(cursor):
    """
    This refresh script expects the legacy schema to have no foreign keys.
    Stop if constraints have been added since the schema was inspected.
    """
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = %s
          AND REFERENCED_TABLE_NAME IS NOT NULL
        """,
        (EXPECTED_DB_NAME,),
    )
    foreign_key_count = cursor.fetchone()[0]

    if foreign_key_count:
        raise RuntimeError(
            f"Found {foreign_key_count} foreign-key relationships in "
            f"{EXPECTED_DB_NAME}. Stop and review delete behavior before "
            "running this full-refresh script."
        )


# ============================================================
# BATCH INSERT HELPER
# ============================================================


def execute_in_batches(cursor, sql, rows, label):
    """Insert records individually using parameterized SQL."""

    total = 0

    for row in rows:
        cursor.execute(sql, row)
        total += 1

        if total % BATCH_SIZE == 0 or total == len(rows):
            print(
                f"{label}: {total:,}/{len(rows):,}",
                flush=True
            )

    return total



# ============================================================
# BUILD DATABASE ROWS
# ============================================================

def build_account_rows(accounts):
    rows = []

    for account in accounts:
        rows.append((
            as_text(account.get("id")),
            account.get("name"),
            account.get("description"),
            parse_datetime(account.get("createdAt") or account.get("created_at")),
            parse_datetime(account.get("lastActive") or account.get("last_active")),
            account.get("karma"),
            account.get("followerCount", account.get("follower_count")),
            account.get("followingCount", account.get("following_count")),
            account.get("isClaimed", account.get("is_claimed")),
            account.get("isActive", account.get("is_active")),
            json_for_mysql(account),
        ))

    return rows


def build_post_rows(posts):
    rows = []

    for post in posts:
        submolt = post.get("submolt")
        if isinstance(submolt, dict):
            submolt_id = submolt.get("id")
            submolt_name = submolt.get("name")
        else:
            submolt_id = None
            submolt_name = submolt

        rows.append((
            as_text(post.get("id")),
            get_account_id(post),
            post.get("title"),
            post.get("content"),
            post.get("type"),
            as_text(submolt_id),
            submolt_name,
            parse_datetime(post.get("created_at") or post.get("createdAt")),
            parse_datetime(post.get("updated_at") or post.get("updatedAt")),
            post.get("comment_count", post.get("commentCount")),
            post.get("verification_status"),
            post.get("is_deleted"),
            post.get("is_spam"),
            json_for_mysql(post),
        ))

    return rows


def build_comment_rows(flat_comments):
    return [
        (
            item["comment_id"],
            item["post_id"],
            item["author_id"],
            item["parent_comment_id"],
            item["content"],
            item["created_at"],
            item["updated_at"],
            item["reply_count"],
            item["depth"],
            item["is_deleted"],
            item["is_spam"],
            item["raw_json"],
        )
        for item in flat_comments
    ]


# ============================================================
# SQL STATEMENTS
# ============================================================

ACCOUNT_INSERT_SQL = """
    INSERT INTO accounts (
        account_id, name, description, created_at, last_active,
        karma, follower_count, following_count, is_claimed, is_active, raw_json
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

POST_INSERT_SQL = """
    INSERT INTO posts (
        post_id, author_id, title, content, post_type,
        submolt_id, submolt_name, created_at, updated_at,
        comment_count, verification_status, is_deleted, is_spam, raw_json
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

COMMENT_INSERT_SQL = """
    INSERT INTO comments (
        comment_id, post_id, author_id, parent_comment_id,
        content, created_at, updated_at, reply_count, depth,
        is_deleted, is_spam, raw_json
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


# ============================================================
# REFRESH AND VERIFY
# ============================================================

def clear_existing_data(cursor):
    """Delete imported records in dependency order."""
    print("\nRemoving existing records...")
    for table in ("comments", "posts", "accounts"):
        cursor.execute(f"DELETE FROM {table}")
        print(f"Deleted {table}: {cursor.rowcount:,}")


def get_table_count(cursor, table):
    """Return a row count for one of the known table names."""
    allowed_tables = {"accounts", "posts", "comments"}
    if table not in allowed_tables:
        raise ValueError(f"Unexpected table name: {table}")

    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]


def verify_counts(cursor, expected):
    """Compare database counts against the expected import counts."""
    print("\nVERIFYING DATABASE COUNTS")

    for table, expected_count in expected.items():
        actual_count = get_table_count(cursor, table)
        print(
            f"{table}: expected {expected_count:,} | "
            f"database {actual_count:,}"
        )

        if actual_count != expected_count:
            raise RuntimeError(
                f"Count mismatch for {table}: expected {expected_count:,}, "
                f"found {actual_count:,}."
            )


def main():
    print("=" * 60)
    print("MOLTBOOK LEGACY DATABASE FULL REFRESH")
    print("=" * 60)
    print(f"Target database: {EXPECTED_DB_NAME}")
    print(f"Raw data folder: {DATA_DIR}")

    # Step 1: Load files before connecting to or modifying MySQL.
    accounts = load_json("accounts.json")
    posts = load_json("posts.json")
    top_level_comments = load_json("comments.json")

    # Step 2: Validate all raw data and relationships.
    flat_comments = validate_raw_data(
        accounts,
        posts,
        top_level_comments,
    )

    # Step 3: Prepare all rows before the database transaction.
    print("\nPreparing database records...")
    account_rows = build_account_rows(accounts)
    post_rows = build_post_rows(posts)
    comment_rows = build_comment_rows(flat_comments)

    expected_counts = {
        "accounts": len(account_rows),
        "posts": len(post_rows),
        "comments": len(comment_rows),
    }

    print("\nIMPORT PREVIEW")
    print(f"Accounts: {expected_counts['accounts']:,}")
    print(f"Posts: {expected_counts['posts']:,}")
    print(f"Comments and replies: {expected_counts['comments']:,}")

    # Step 4: Require explicit confirmation before deleting old rows.
    print(
        "\nWARNING: This will replace all existing accounts, posts, and "
        "comments in moltbook_research."
    )
    confirmation = input(
        f"Type REFRESH to continue with {EXPECTED_DB_NAME}: "
    ).strip()

    if confirmation != "REFRESH":
        print("Refresh cancelled. No database records were changed.")
        return

    connection = None
    cursor = None

    try:
        # Step 5: Connect and check database constraints.
        connection = connect_db()
        cursor = connection.cursor(prepared=True)
        ensure_no_foreign_keys(cursor)

        # Step 6: Start transaction and refresh.
       # Step 6: Refresh within the active transaction.
        clear_existing_data(cursor)
        print("\nImporting accounts...")
        execute_in_batches(
            cursor, ACCOUNT_INSERT_SQL, account_rows, "Accounts"
        )

        print("\nImporting posts...")
        execute_in_batches(
            cursor, POST_INSERT_SQL, post_rows, "Posts"
        )

        print("\nImporting comments and replies...")
        execute_in_batches(
            cursor, COMMENT_INSERT_SQL, comment_rows, "Comments"
        )

        # Step 7: Verify before committing.
        verify_counts(cursor, expected_counts)

        connection.commit()

        print("\n" + "=" * 60)
        print("DATABASE REFRESH COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print_database_summary(cursor)

    except Exception:
        if connection is not None and connection.is_connected():
            connection.rollback()
        print("\nIMPORT FAILED. The transaction was rolled back.")
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()

        print("\nDatabase connection closed.")


def print_database_summary(cursor):
    """Print final counts after a successful commit."""
    print("\nFINAL DATABASE COUNTS")
    for table in ("accounts", "posts", "comments"):
        total = get_table_count(cursor, table)
        print(f"{table}: {total:,}")

    cursor.execute("SELECT COUNT(*) FROM collection_runs")
    print(f"collection_runs: {cursor.fetchone()[0]:,} (not modified)")


if __name__ == "__main__":
    main()
