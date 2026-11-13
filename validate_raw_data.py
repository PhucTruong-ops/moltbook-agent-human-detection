
"""
Moltbook Raw Data Validation

Validates:
1. Account IDs
2. Post IDs
3. Comment and nested reply IDs
4. Post author references
5. Comment author references
6. Comment-to-post references
7. Parent-comment references

Run from the repository root:
    python validate_raw_data.py
"""

import json
from collections import Counter
from pathlib import Path


# ============================================================
# 1. CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

ACCOUNTS_FILE = RAW_DIR / "accounts.json"
POSTS_FILE = RAW_DIR / "posts.json"
COMMENTS_FILE = RAW_DIR / "comments.json"


# ============================================================
# 2. GENERAL HELPERS
# ============================================================

def load_json(path):
    """Load a JSON file and ensure its contents are a list."""

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(f"{path.name} must contain a JSON list.")

    return data


def normalize_id(value):
    """Convert an ID to a clean string or return None."""

    if value is None:
        return None

    value = str(value).strip()

    return value if value else None


def get_author_id(record):
    """Get author ID from a direct field or embedded profile."""

    author = record.get("author")

    embedded_id = (
        author.get("id")
        if isinstance(author, dict)
        else None
    )

    return (
        normalize_id(record.get("author_id"))
        or normalize_id(embedded_id)
    )


def duplicate_ids(ids):
    """Return IDs that occur more than once."""

    counts = Counter(ids)

    return {
        item: count
        for item, count in counts.items()
        if count > 1
    }


def show_examples(items, limit=10):
    """Print a limited number of examples."""

    for item in list(items)[:limit]:
        print(f"  - {item}")


# ============================================================
# 3. LOAD RAW DATA
# ============================================================

print("=" * 65)
print("MOLTBOOK RAW DATA VALIDATION")
print("=" * 65)

accounts = load_json(ACCOUNTS_FILE)
posts = load_json(POSTS_FILE)
comments = load_json(COMMENTS_FILE)

print("\nRAW DATA LOADED")
print(f"Account records: {len(accounts):,}")
print(f"Post records: {len(posts):,}")
print(f"Top-level comment records: {len(comments):,}")


# ============================================================
# 4. VALIDATE ACCOUNT IDS
# ============================================================

print("\n" + "=" * 65)
print("1. ACCOUNT ID VALIDATION")
print("=" * 65)

valid_accounts = [
    account
    for account in accounts
    if isinstance(account, dict)
]

malformed_accounts = len(accounts) - len(valid_accounts)

account_ids = [
    normalize_id(account.get("id"))
    for account in valid_accounts
]

missing_account_ids = sum(
    account_id is None
    for account_id in account_ids
)

valid_account_ids = [
    account_id
    for account_id in account_ids
    if account_id is not None
]

duplicate_account_ids = duplicate_ids(valid_account_ids)

account_id_set = set(valid_account_ids)

print(f"Account records: {len(accounts):,}")
print(f"Malformed records: {malformed_accounts:,}")
print(f"Missing account IDs: {missing_account_ids:,}")
print(f"Unique account IDs: {len(account_id_set):,}")
print(f"Duplicate account IDs: {len(duplicate_account_ids):,}")


# ============================================================
# 5. VALIDATE POST IDS
# ============================================================

print("\n" + "=" * 65)
print("2. POST ID VALIDATION")
print("=" * 65)

valid_posts = [
    post
    for post in posts
    if isinstance(post, dict)
]

malformed_posts = len(posts) - len(valid_posts)

post_ids = [
    normalize_id(post.get("id"))
    for post in valid_posts
]

missing_post_ids = sum(
    post_id is None
    for post_id in post_ids
)

valid_post_ids = [
    post_id
    for post_id in post_ids
    if post_id is not None
]

duplicate_post_ids = duplicate_ids(valid_post_ids)

post_id_set = set(valid_post_ids)

print(f"Post records: {len(posts):,}")
print(f"Malformed records: {malformed_posts:,}")
print(f"Missing post IDs: {missing_post_ids:,}")
print(f"Unique post IDs: {len(post_id_set):,}")
print(f"Duplicate post IDs: {len(duplicate_post_ids):,}")


# ============================================================
# 6. VALIDATE POST AUTHORS
# ============================================================

print("\n" + "=" * 65)
print("3. POST AUTHOR VALIDATION")
print("=" * 65)

post_author_ids = [
    get_author_id(post)
    for post in valid_posts
]

posts_without_author = sum(
    author_id is None
    for author_id in post_author_ids
)

missing_post_authors = {
    author_id
    for author_id in post_author_ids
    if author_id is not None
    and author_id not in account_id_set
}

print(f"Posts without author IDs: {posts_without_author:,}")
print(f"Unique missing author IDs: {len(missing_post_authors):,}")

if missing_post_authors:
    print("Examples:")
    show_examples(missing_post_authors)


# ============================================================
# 7. RECURSIVELY VALIDATE COMMENTS AND REPLIES
# ============================================================

print("\n" + "=" * 65)
print("4. COMMENT AND REPLY VALIDATION")
print("=" * 65)

all_comment_ids = []
comment_author_ids = set()
comment_post_ids = set()
parent_relationships = []

comments_without_id = 0
comments_without_author = 0
comments_without_post = 0

malformed_comments = 0
malformed_replies_fields = 0

top_level_count = 0
nested_reply_count = 0


def inspect_comments(
    comment_list,
    parent_id=None,
    inherited_post_id=None,
    is_nested=False
):
    """
    Recursively inspect comments and nested replies.

    Nested replies inherit the post ID from their parent
    when their own post_id is missing.

    The structural parent is used when an explicit parent
    ID is not provided.
    """

    global comments_without_id
    global comments_without_author
    global comments_without_post
    global malformed_comments
    global malformed_replies_fields
    global nested_reply_count

    if not isinstance(comment_list, list):

        malformed_comments += 1
        return

    for comment in comment_list:

        if not isinstance(comment, dict):

            malformed_comments += 1
            continue

        if is_nested:
            nested_reply_count += 1

        # --------------------------------------------
        # Comment ID
        # --------------------------------------------

        comment_id = normalize_id(
            comment.get("id")
        )

        if comment_id is None:

            comments_without_id += 1

        else:

            all_comment_ids.append(comment_id)

        # --------------------------------------------
        # Author ID
        # --------------------------------------------

        author_id = get_author_id(comment)

        if author_id is None:

            comments_without_author += 1

        else:

            comment_author_ids.add(author_id)

        # --------------------------------------------
        # Post ID
        # --------------------------------------------

        post_id = (
            normalize_id(comment.get("post_id"))
            or inherited_post_id
        )

        if post_id is None:

            comments_without_post += 1

        else:

            comment_post_ids.add(post_id)

        # --------------------------------------------
        # Parent relationship
        # --------------------------------------------

        explicit_parent = normalize_id(
            comment.get("parent_comment_id")
            or comment.get("parent_id")
        )

        actual_parent_id = (
            explicit_parent
            or parent_id
        )

        if actual_parent_id is not None:

            parent_relationships.append(
                (comment_id, actual_parent_id)
            )

        # --------------------------------------------
        # Nested replies
        # --------------------------------------------

        replies = comment.get("replies", [])

        if replies is None:
            replies = []

        if not isinstance(replies, list):

            malformed_replies_fields += 1
            continue

        if replies:

            inspect_comments(
                replies,
                parent_id=comment_id,
                inherited_post_id=post_id,
                is_nested=True
            )


top_level_count = len(comments)

inspect_comments(comments)

comment_id_set = set(all_comment_ids)

duplicate_comment_ids = duplicate_ids(
    all_comment_ids
)

print(f"Top-level comments: {top_level_count:,}")
print(f"Nested replies: {nested_reply_count:,}")
print(
    f"Total comments and replies: "
    f"{len(all_comment_ids):,}"
)
print(f"Unique comment IDs: {len(comment_id_set):,}")
print(f"Duplicate comment IDs: {len(duplicate_comment_ids):,}")
print(f"Missing comment IDs: {comments_without_id:,}")
print(f"Missing comment author IDs: {comments_without_author:,}")
print(f"Missing comment post IDs: {comments_without_post:,}")
print(f"Malformed comment records: {malformed_comments:,}")
print(f"Invalid replies fields: {malformed_replies_fields:,}")


# ============================================================
# 8. VALIDATE COMMENT AUTHORS
# ============================================================

print("\n" + "=" * 65)
print("5. COMMENT AUTHOR REFERENCES")
print("=" * 65)

missing_comment_authors = (
    comment_author_ids - account_id_set
)

print(
    f"Unique comment author IDs: "
    f"{len(comment_author_ids):,}"
)

print(
    f"Authors missing from accounts: "
    f"{len(missing_comment_authors):,}"
)

if missing_comment_authors:
    print("Examples:")
    show_examples(missing_comment_authors)


# ============================================================
# 9. VALIDATE COMMENT-TO-POST REFERENCES
# ============================================================

print("\n" + "=" * 65)
print("6. COMMENT-TO-POST REFERENCES")
print("=" * 65)

missing_comment_posts = (
    comment_post_ids - post_id_set
)

print(
    f"Unique comment post IDs: "
    f"{len(comment_post_ids):,}"
)

print(
    f"Post IDs missing from posts: "
    f"{len(missing_comment_posts):,}"
)

if missing_comment_posts:
    print("Examples:")
    show_examples(missing_comment_posts)


# ============================================================
# 10. VALIDATE PARENT-COMMENT REFERENCES
# ============================================================

print("\n" + "=" * 65)
print("7. PARENT-COMMENT REFERENCES")
print("=" * 65)

missing_parent_ids = {
    parent_id
    for comment_id, parent_id in parent_relationships
    if parent_id not in comment_id_set
}

print(
    f"Comments with parent relationships: "
    f"{len(parent_relationships):,}"
)

print(
    f"Parent IDs missing from comment dataset: "
    f"{len(missing_parent_ids):,}"
)

if missing_parent_ids:
    print("Examples:")
    show_examples(missing_parent_ids)


# ============================================================
# 11. FINAL VALIDATION SUMMARY
# ============================================================

print("\n" + "=" * 65)
print("FINAL VALIDATION SUMMARY")
print("=" * 65)

checks = {
    "Account IDs": (
        missing_account_ids == 0
        and len(duplicate_account_ids) == 0
        and malformed_accounts == 0
    ),
    "Post IDs": (
        missing_post_ids == 0
        and len(duplicate_post_ids) == 0
        and malformed_posts == 0
    ),
    "Post authors": (
        posts_without_author == 0
        and len(missing_post_authors) == 0
    ),
    "Comment IDs": (
        comments_without_id == 0
        and len(duplicate_comment_ids) == 0
    ),
    "Comment authors": (
        comments_without_author == 0
        and len(missing_comment_authors) == 0
    ),
    "Comment post references": (
        comments_without_post == 0
        and len(missing_comment_posts) == 0
    ),
    "Parent-comment references": (
        len(missing_parent_ids) == 0
    ),
    "Comment structure": (
        malformed_comments == 0
        and malformed_replies_fields == 0
    )
}

for check_name, passed in checks.items():

    status = "PASS" if passed else "FAIL"

    print(f"{check_name}: {status}")

passed_count = sum(checks.values())
total_checks = len(checks)

print(
    f"\nValidation checks passed: "
    f"{passed_count}/{total_checks}"
)

if passed_count == total_checks:

    print("\nALL VALIDATION CHECKS PASSED.")

else:

    print("\nVALIDATION NEEDS ATTENTION.")

    print(
        "Do not refresh the database until all failures "
        "have been investigated."
    )
