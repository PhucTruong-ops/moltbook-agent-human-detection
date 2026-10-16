
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

# Project root is the parent directory of src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"

load_dotenv(PROJECT_ROOT / ".env")


def parse_datetime(value):
    """Convert ISO timestamps to MySQL-compatible UTC datetimes."""
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

        return parsed
    except (ValueError, TypeError):
        return None


def load_json(filename):
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"{filename} must contain a JSON list.")

    return data


def connect_db():
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            f"Missing database settings in .env: {', '.join(missing)}"
        )

    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def import_accounts(cursor, accounts):
    sql = """
        INSERT INTO accounts (
            account_id, name, description, created_at, last_active,
            karma, follower_count, following_count,
            is_claimed, is_active, raw_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            description = VALUES(description),
            created_at = VALUES(created_at),
            last_active = VALUES(last_active),
            karma = VALUES(karma),
            follower_count = VALUES(follower_count),
            following_count = VALUES(following_count),
            is_claimed = VALUES(is_claimed),
            is_active = VALUES(is_active),
            raw_json = VALUES(raw_json)
    """

    count = 0

    for account in accounts:
        account_id = account.get("id")
        if not account_id:
            continue

        cursor.execute(sql, (
            account_id,
            account.get("name"),
            account.get("description"),
            parse_datetime(account.get("createdAt") or account.get("created_at")),
            parse_datetime(account.get("lastActive") or account.get("last_active")),
            account.get("karma"),
            account.get("followerCount", account.get("follower_count")),
            account.get("followingCount", account.get("following_count")),
            account.get("isClaimed", account.get("is_claimed")),
            account.get("isActive", account.get("is_active")),
            json.dumps(account, ensure_ascii=False),
        ))
        count += 1

    return count


def import_posts(cursor, posts):
    sql = """
        INSERT INTO posts (
            post_id, author_id, title, content, post_type,
            submolt_id, submolt_name, created_at, updated_at,
            comment_count, verification_status, is_deleted, is_spam,
            raw_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            author_id = VALUES(author_id),
            title = VALUES(title),
            content = VALUES(content),
            post_type = VALUES(post_type),
            submolt_id = VALUES(submolt_id),
            submolt_name = VALUES(submolt_name),
            created_at = VALUES(created_at),
            updated_at = VALUES(updated_at),
            comment_count = VALUES(comment_count),
            verification_status = VALUES(verification_status),
            is_deleted = VALUES(is_deleted),
            is_spam = VALUES(is_spam),
            raw_json = VALUES(raw_json)
    """

    count = 0

    for post in posts:
        post_id = post.get("id")
        if not post_id:
            continue

        author = post.get("author") or {}
        submolt = post.get("submolt") or {}

        cursor.execute(sql, (
            post_id,
            post.get("author_id") or author.get("id"),
            post.get("title"),
            post.get("content"),
            post.get("type"),
            submolt.get("id"),
            submolt.get("name") if isinstance(submolt, dict) else submolt,
            parse_datetime(post.get("created_at") or post.get("createdAt")),
            parse_datetime(post.get("updated_at") or post.get("updatedAt")),
            post.get("comment_count", post.get("commentCount")),
            post.get("verification_status"),
            post.get("is_deleted"),
            post.get("is_spam"),
            json.dumps(post, ensure_ascii=False),
        ))
        count += 1

    return count


def import_comments(cursor, comments):
    sql = """
        INSERT INTO comments (
            comment_id, post_id, author_id, parent_comment_id,
            content, created_at, updated_at, reply_count, depth,
            is_deleted, is_spam, raw_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            post_id = VALUES(post_id),
            author_id = VALUES(author_id),
            parent_comment_id = VALUES(parent_comment_id),
            content = VALUES(content),
            created_at = VALUES(created_at),
            updated_at = VALUES(updated_at),
            reply_count = VALUES(reply_count),
            depth = VALUES(depth),
            is_deleted = VALUES(is_deleted),
            is_spam = VALUES(is_spam),
            raw_json = VALUES(raw_json)
    """

    count = 0

    for comment in comments:
        comment_id = comment.get("id")
        if not comment_id:
            continue

        author = comment.get("author") or {}

        cursor.execute(sql, (
            comment_id,
            comment.get("post_id"),
            comment.get("author_id") or author.get("id"),
            comment.get("parent_id") or comment.get("parent_comment_id"),
            comment.get("content"),
            parse_datetime(comment.get("created_at") or comment.get("createdAt")),
            parse_datetime(comment.get("updated_at") or comment.get("updatedAt")),
            comment.get("reply_count", comment.get("replyCount")),
            comment.get("depth"),
            comment.get("is_deleted"),
            comment.get("is_spam"),
            json.dumps(comment, ensure_ascii=False),
        ))
        count += 1

    return count


def main():
    # Load everything before opening the database transaction.
    accounts = load_json("accounts.json")
    posts = load_json("posts.json")
    comments = load_json("comments.json")

    connection = connect_db()

    try:
        cursor = connection.cursor()

        account_count = import_accounts(cursor, accounts)
        post_count = import_posts(cursor, posts)
        comment_count = import_comments(cursor, comments)

        connection.commit()

        print("Import completed successfully.")
        print(f"Account records processed: {account_count}")
        print(f"Post records processed: {post_count}")
        print(f"Comment records processed: {comment_count}")

        for table in ("accounts", "posts", "comments"):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"Total rows in {table}: {cursor.fetchone()[0]}")

        cursor.close()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()

