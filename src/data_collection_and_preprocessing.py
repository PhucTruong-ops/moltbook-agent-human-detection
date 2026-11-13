"""
Moltbook Data Collection and Preprocessing Pipeline

Pipeline:
1. Collect posts from the Moltbook API.
2. Collect comments and nested replies.
3. Extract unique accounts from posts, comments, and replies.
4. Clean posts and generate data-quality reports.

Run from the repository root:
    python src/data_collection_and_preprocessing.py
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests


# ============================================================
# 1. CONFIGURATION
# ============================================================

BASE_URL = "https://www.moltbook.com/api/v1"

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")

POSTS_FILE = RAW_DIR / "posts.json"
POSTS_TEMP_FILE = RAW_DIR / "posts.tmp.json"

COMMENTS_FILE = RAW_DIR / "comments.json"
COMMENTS_PROGRESS_FILE = RAW_DIR / "comments_progress.json"
COMMENT_REPORT_FILE = PROCESSED_DIR / "comment_collection_report.txt"

ACCOUNTS_FILE = RAW_DIR / "accounts.json"
ACCOUNT_REPORT_FILE = PROCESSED_DIR / "account_extraction_report.txt"

CLEANED_POSTS_FILE = PROCESSED_DIR / "posts_cleaned.csv"
CLEANING_REPORT_FILE = PROCESSED_DIR / "cleaning_report.txt"
MISSING_VALUES_FILE = PROCESSED_DIR / "missing_values_by_field.csv"

TARGET_TOTAL = 20_000
PAGE_SIZE = 25
REQUEST_DELAY = 1.1
MAX_RETRIES = 5


# ============================================================
# 2. SHARED JSON FUNCTIONS
# ============================================================

def load_json(path, default):
    """Load JSON from a file or return a default value."""

    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    """Save JSON safely using a temporary file."""

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.with_suffix(path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp_path.replace(path)


def request_json(session, url, params):
    """Request an API page with retry and rate-limit handling."""

    for attempt in range(MAX_RETRIES):

        try:
            response = session.get(
                url,
                params=params,
                timeout=30
            )

            if response.status_code == 429:

                retry_after = response.headers.get("Retry-After")

                try:
                    wait_seconds = float(retry_after)

                except (TypeError, ValueError):
                    wait_seconds = min(
                        2 ** (attempt + 1),
                        60
                    )

                print(
                    f"Rate limited. Waiting "
                    f"{wait_seconds:g} seconds."
                )

                time.sleep(wait_seconds)
                continue

            response.raise_for_status()

            payload = response.json()

            if not isinstance(payload, dict):
                raise ValueError(
                    "API response was not a JSON object."
                )

            return payload

        except (
            requests.RequestException,
            ValueError
        ) as error:

            if attempt == MAX_RETRIES - 1:
                raise

            wait_seconds = min(
                2 ** (attempt + 1),
                60
            )

            print(f"Request failed: {error}")
            print(f"Retrying in {wait_seconds} seconds...")

            time.sleep(wait_seconds)

    raise RuntimeError("Maximum request retries reached.")


# ============================================================
# 3. POST COLLECTION
# ============================================================

def save_posts(posts_by_id):
    """Save collected posts safely after each page."""

    records = list(posts_by_id.values())

    with POSTS_TEMP_FILE.open("w", encoding="utf-8") as file:

        json.dump(
            records,
            file,
            ensure_ascii=False,
            indent=2
        )

    POSTS_TEMP_FILE.replace(POSTS_FILE)


def collect_posts(
    target_total=TARGET_TOTAL,
    page_size=PAGE_SIZE
):
    """
    Collect posts using cursor pagination.

    Existing posts are loaded first so collection can resume.
    Duplicate post IDs are updated instead of duplicated.
    """

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    posts_by_id = {}

    if POSTS_FILE.exists():

        existing_posts = load_json(
            POSTS_FILE,
            []
        )

        if not isinstance(existing_posts, list):
            raise ValueError(
                "Expected posts.json to contain a list."
            )

        for post in existing_posts:

            if not isinstance(post, dict):
                continue

            post_id = post.get("id")

            if post_id:
                posts_by_id[str(post_id)] = post

        print(
            f"Loaded {len(posts_by_id)} existing unique posts."
        )

    if len(posts_by_id) >= target_total:

        print(
            f"Post target already reached: "
            f"{len(posts_by_id)} of {target_total}."
        )

        return

    session = requests.Session()

    cursor = None
    seen_cursors = set()
    pages_fetched = 0

    try:

        while len(posts_by_id) < target_total:

            params = {
                "sort": "new",
                "limit": page_size
            }

            if cursor:
                params["cursor"] = cursor

            payload = request_json(
                session,
                f"{BASE_URL}/posts",
                params
            )

            if not payload.get("success"):

                raise RuntimeError(
                    f"Moltbook API returned an unsuccessful "
                    f"response: {payload}"
                )

            posts = payload.get("posts", [])

            if not isinstance(posts, list):
                raise ValueError(
                    "API posts field was not a list."
                )

            pages_fetched += 1
            new_ids = 0

            for post in posts:

                if not isinstance(post, dict):
                    continue

                post_id = post.get("id")

                if not post_id:
                    continue

                post_id = str(post_id)

                if post_id not in posts_by_id:
                    new_ids += 1

                posts_by_id[post_id] = post

            save_posts(posts_by_id)

            print(
                f"Page {pages_fetched}: "
                f"received {len(posts)} posts; "
                f"{new_ids} new unique IDs; "
                f"{len(posts_by_id)} unique posts saved."
            )

            next_cursor = payload.get("next_cursor")

            if len(posts_by_id) >= target_total:
                break

            if not payload.get("has_more") or not next_cursor:

                print("API reports no more pages.")
                break

            if (
                next_cursor in seen_cursors
                or next_cursor == cursor
            ):

                raise RuntimeError(
                    "Post pagination returned a repeated cursor. "
                    "Stopping to avoid an infinite loop."
                )

            seen_cursors.add(next_cursor)
            cursor = next_cursor

            time.sleep(REQUEST_DELAY)

    finally:
        session.close()

    print("\nPost collection finished.")
    print(f"Unique posts saved: {len(posts_by_id)}")
    print(f"Target: {target_total}")
    print(f"File: {POSTS_FILE}")


# ============================================================
# 4. COMMENT COLLECTION
# ============================================================

def collect_comments():
    """
    Collect comments for every post.

    Supports:
    - Cursor pagination
    - Retry handling
    - Duplicate comment removal
    - Progress tracking
    - Resuming previously completed posts
    """

    if not POSTS_FILE.exists():

        raise FileNotFoundError(
            f"Posts file not found: {POSTS_FILE}. "
            "Run post collection first."
        )

    posts = load_json(POSTS_FILE, [])

    if not isinstance(posts, list):
        raise ValueError(
            "Expected posts.json to contain a list."
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    valid_posts = [
        post
        for post in posts
        if isinstance(post, dict)
        and post.get("id") is not None
        and str(post.get("id")).strip()
    ]

    posts_by_id = {
        str(post["id"]).strip(): post
        for post in valid_posts
    }

    comments = load_json(
        COMMENTS_FILE,
        []
    )

    if not isinstance(comments, list):
        raise ValueError(
            "Expected comments.json to contain a list."
        )

    comments_by_id = {}
    missing_comment_ids = 0

    for comment in comments:

        if not isinstance(comment, dict):
            continue

        comment_id = comment.get("id")

        if (
            comment_id is not None
            and str(comment_id).strip()
        ):

            comments_by_id[
                str(comment_id).strip()
            ] = comment

        else:
            missing_comment_ids += 1

    progress = load_json(
        COMMENTS_PROGRESS_FILE,
        {
            "completed_post_ids": [],
            "failed_post_ids": []
        }
    )

    completed_ids = set(
        progress.get("completed_post_ids", [])
    )

    failed_ids = set(
        progress.get("failed_post_ids", [])
    )

    completed_ids.intersection_update(
        posts_by_id.keys()
    )

    failed_ids.intersection_update(
        posts_by_id.keys()
    )

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
            posts_by_id.items(),
            start=1
        ):

            if post_id in completed_ids:
                continue

            url = (
                f"{BASE_URL}/posts/"
                f"{post_id}/comments"
            )

            cursor = None
            post_had_comments = False
            post_succeeded = True
            seen_cursors = set()

            try:

                while True:

                    params = {
                        "limit": PAGE_SIZE,
                        "sort": "new"
                    }

                    if cursor:
                        params["cursor"] = cursor

                    payload = request_json(
                        session,
                        url,
                        params
                    )

                    if not payload.get("success"):

                        raise RuntimeError(
                            f"API reported failure for post {post_id}."
                        )

                    page_comments = payload.get(
                        "comments",
                        []
                    )

                    if not isinstance(page_comments, list):

                        raise ValueError(
                            f"Invalid comments field for post {post_id}."
                        )

                    pages_fetched += 1

                    for comment in page_comments:

                        if not isinstance(comment, dict):
                            continue

                        comment_id = comment.get("id")

                        if (
                            comment_id is None
                            or not str(comment_id).strip()
                        ):

                            comments_missing_ids_this_run += 1
                            continue

                        comment_id = str(comment_id).strip()

                        comments_by_id[comment_id] = comment

                        post_had_comments = True

                    if not payload.get("has_more"):
                        break

                    next_cursor = payload.get("next_cursor")

                    if (
                        not next_cursor
                        or next_cursor in seen_cursors
                        or next_cursor == cursor
                    ):

                        raise RuntimeError(
                            f"Pagination stopped unexpectedly "
                            f"for post {post_id}."
                        )

                    seen_cursors.add(next_cursor)
                    cursor = next_cursor

                    time.sleep(REQUEST_DELAY)

            except (
                requests.RequestException,
                ValueError,
                RuntimeError
            ) as error:

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

            # Save comments and progress after every post.
            save_json(
                COMMENTS_FILE,
                list(comments_by_id.values())
            )

            save_json(
                COMMENTS_PROGRESS_FILE,
                {
                    "completed_post_ids": sorted(completed_ids),
                    "failed_post_ids": sorted(failed_ids)
                }
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
        f"Comments without IDs found in existing file: {missing_comment_ids}",
        f"Output file: {COMMENTS_FILE}",
        f"Progress file: {COMMENTS_PROGRESS_FILE}",
        "",
        "Note: zero comments means the API returned no comments for a",
        "successfully completed post; it does not mean the request failed.",
        "Posts still marked failed should be retried and investigated."
    ]

    COMMENT_REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8"
    )

    print("\n" + "\n".join(report))

    # ============================================================
# 5. ACCOUNT EXTRACTION
# ============================================================

def extract_accounts():
    """
    Extract unique account profiles from:
    - Post authors
    - Comment authors
    - Nested comment replies

    Author IDs without embedded profiles are tracked separately.
    No account profiles are fabricated.
    """

    if not POSTS_FILE.exists():
        raise FileNotFoundError(
            f"Posts file not found: {POSTS_FILE}"
        )

    if not COMMENTS_FILE.exists():
        raise FileNotFoundError(
            f"Comments file not found: {COMMENTS_FILE}"
        )

    posts = load_json(POSTS_FILE, [])
    comments = load_json(COMMENTS_FILE, [])

    if not isinstance(posts, list):
        raise ValueError(
            "Expected posts.json to contain a list."
        )

    if not isinstance(comments, list):
        raise ValueError(
            "Expected comments.json to contain a list."
        )

    accounts_by_id = {}

    post_author_ids = set()
    comment_author_ids = set()
    comment_profile_ids = set()
    author_ids_without_profiles = set()

    malformed_posts = 0
    posts_without_author_objects = 0
    comments_examined = 0
    malformed_comments = 0
    missing_author_ids = 0

    def normalize_id(value):
        """Convert an ID into a clean string."""

        if value is None:
            return None

        value = str(value).strip()

        return value if value else None

    def add_profile(author, fallback_id=None):
        """
        Add an account profile if its ID has not been collected.

        The first available profile is preserved.
        """

        if not isinstance(author, dict):
            return None

        account_id = (
            normalize_id(author.get("id"))
            or normalize_id(fallback_id)
        )

        if account_id is None:
            return None

        if account_id not in accounts_by_id:

            profile = dict(author)
            profile["id"] = account_id

            accounts_by_id[account_id] = profile

        return account_id

    # --------------------------------------------------------
    # A. Extract accounts from posts
    # --------------------------------------------------------

    for post in posts:

        if not isinstance(post, dict):

            malformed_posts += 1
            continue

        author = post.get("author")
        fallback_id = post.get("author_id")

        if not isinstance(author, dict):

            posts_without_author_objects += 1

            account_id = normalize_id(fallback_id)

            if account_id:

                post_author_ids.add(account_id)

                author_ids_without_profiles.add(account_id)

            else:

                missing_author_ids += 1

            continue

        account_id = add_profile(
            author,
            fallback_id
        )

        if account_id:

            post_author_ids.add(account_id)

        else:

            missing_author_ids += 1

    # --------------------------------------------------------
    # B. Extract accounts from comments and nested replies
    # --------------------------------------------------------

    def visit_comments(comment_list):
        """
        Recursively inspect comment authors and nested replies.
        """

        nonlocal comments_examined
        nonlocal malformed_comments
        nonlocal missing_author_ids

        for comment in comment_list:

            if not isinstance(comment, dict):

                malformed_comments += 1
                continue

            comments_examined += 1

            author = comment.get("author")
            fallback_id = comment.get("author_id")

            if isinstance(author, dict):

                account_id = add_profile(
                    author,
                    fallback_id
                )

                if account_id:

                    comment_author_ids.add(account_id)
                    comment_profile_ids.add(account_id)

                else:

                    missing_author_ids += 1

            else:

                account_id = normalize_id(fallback_id)

                if account_id:

                    comment_author_ids.add(account_id)

                    author_ids_without_profiles.add(account_id)

                else:

                    missing_author_ids += 1

            # Recursively inspect nested replies.
            replies = comment.get("replies", [])

            if isinstance(replies, list) and replies:

                visit_comments(replies)

    visit_comments(comments)

    # --------------------------------------------------------
    # C. Save accounts and extraction report
    # --------------------------------------------------------

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    save_json(
        ACCOUNTS_FILE,
        list(accounts_by_id.values())
    )

    all_author_ids = (
        post_author_ids | comment_author_ids
    )

    report = [
        "Moltbook Account Extraction Report",
        "==================================",
        f"Posts examined: {len(posts)}",
        f"Malformed post records: {malformed_posts}",
        f"Posts without embedded author objects: {posts_without_author_objects}",
        f"Comments and nested replies examined: {comments_examined}",
        f"Malformed comment records: {malformed_comments}",
        "",
        "ACCOUNT RESULTS",
        f"Unique author IDs found in posts: {len(post_author_ids)}",
        f"Unique author IDs found in comments/replies: {len(comment_author_ids)}",
        f"Unique author IDs across posts and comments: {len(all_author_ids)}",
        f"Unique account profiles extracted: {len(accounts_by_id)}",
        f"Comment author profiles found: {len(comment_profile_ids)}",
        f"Author IDs without an embedded profile: {len(author_ids_without_profiles)}",
        f"Records with no usable author ID: {missing_author_ids}",
        f"Output file: {ACCOUNTS_FILE}",
        "",
        "Notes:",
        "- Profiles are extracted from embedded post/comment author objects.",
        "- Nested replies are traversed recursively.",
        "- Author IDs without profiles are counted but not converted into",
        "  fabricated account profiles.",
        "- This represents accounts observed in the collected dataset,",
        "  not every account on Moltbook."
    ]

    ACCOUNT_REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8"
    )

    print("\n" + "\n".join(report))


# ============================================================
# 6. POST CLEANING AND DATA-QUALITY REPORTING
# ============================================================

def is_missing(series):
    """Identify null values and blank strings."""

    return (
        series.isna()
        | series.astype("string").str.strip().eq("").fillna(False)
    )


def parse_boolean(value):
    """Safely parse common boolean values from API data."""

    if pd.isna(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):

        value = value.strip().lower()

        if value in {"true", "1", "yes"}:
            return True

        if value in {"false", "0", "no", ""}:
            return False

    return False


def record_fingerprint(record):
    """Serialize nested data consistently for duplicate detection."""

    return json.dumps(
        record,
        sort_keys=True,
        ensure_ascii=False,
        default=str
    )


def clean_posts():
    """Create cleaned post CSV and data-quality reports."""

    if not POSTS_FILE.exists():

        raise FileNotFoundError(
            f"Input file not found: {POSTS_FILE}. "
            "Run post collection first."
        )

    records = load_json(
        POSTS_FILE,
        []
    )

    if not isinstance(records, list):

        raise ValueError(
            "Expected posts.json to contain a JSON list."
        )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    initial_count = len(records)

    valid_records = [
        record
        for record in records
        if isinstance(record, dict)
    ]

    malformed_count = (
        initial_count - len(valid_records)
    )

    if not valid_records:

        report = [
            "Moltbook Data Quality Report",
            "============================",
            f"Input records: {initial_count}",
            f"Malformed non-object records: {malformed_count}",
            "No valid post objects were available for analysis."
        ]

        CLEANING_REPORT_FILE.write_text(
            "\n".join(report) + "\n",
            encoding="utf-8"
        )

        print("\n".join(report))

        return

    # Include required fields even if completely absent from the API data.
    original_fields = sorted(
        {
            field
            for record in valid_records
            for field in record.keys()
        }
        | {
            "id",
            "title",
            "content",
            "author_id",
            "created_at"
        }
    )

    df = pd.DataFrame(valid_records)

    initial_valid_count = len(df)

    required_fields = [
        "id",
        "title",
        "content",
        "author_id",
        "created_at"
    ]

    for field in required_fields:

        if field not in df.columns:
            df[field] = pd.NA

    df["id"] = (
        df["id"]
        .astype("string")
        .str.strip()
    )

    missing_id = is_missing(df["id"])
    missing_title = is_missing(df["title"])
    missing_content = is_missing(df["content"])
    missing_author = is_missing(df["author_id"])

    duplicate_id = (
        df["id"].notna()
        & df["id"].ne("")
        & df["id"].duplicated(keep="first")
    )

    fingerprints = pd.Series(
        [
            record_fingerprint(record)
            for record in valid_records
        ],
        index=df.index,
        dtype="string"
    )

    exact_duplicate = fingerprints.duplicated(
        keep="first"
    )

    parsed_time = pd.to_datetime(
        df["created_at"],
        errors="coerce",
        utc=True
    )

    invalid_timestamp = parsed_time.isna()

    df["created_at"] = parsed_time

    df["missing_id"] = missing_id
    df["duplicate_id"] = duplicate_id
    df["exact_duplicate_record"] = exact_duplicate
    df["missing_title"] = missing_title
    df["missing_content"] = missing_content
    df["missing_author_id"] = missing_author
    df["invalid_timestamp"] = invalid_timestamp

    for field in ["is_deleted", "is_spam"]:

        if field in df.columns:

            df[f"{field}_flag"] = df[field].map(
                parse_boolean
            )

    title_text = (
        df["title"]
        .fillna("")
        .astype(str)
    )

    content_text = (
        df["content"]
        .fillna("")
        .astype(str)
    )

    df["title_length_chars"] = title_text.str.len()

    df["content_length_chars"] = content_text.str.len()

    df["content_word_count"] = (
        content_text.str.split().str.len()
    )

    df["empty_content"] = (
        content_text.str.strip().eq("")
    )

    # Exclude only missing IDs and repeated IDs.
    # Other quality issues remain flagged for analysis.
    keep = ~missing_id & ~duplicate_id

    cleaned = df.loc[keep].copy()

    cleaned.to_csv(
        CLEANED_POSTS_FILE,
        index=False
    )

    # --------------------------------------------------------
    # Missing-value summary
    # --------------------------------------------------------

    missing_rows = []

    for field in original_fields:

        if field in df.columns:

            missing_count = int(
                is_missing(df[field]).sum()
            )

        else:

            missing_count = len(df)

        missing_rows.append({
            "field": field,
            "missing_count": missing_count,
            "missing_percent": round(
                missing_count / initial_valid_count * 100,
                2
            ) if initial_valid_count else 0
        })

    missing_summary = pd.DataFrame(
        missing_rows
    )

    if not missing_summary.empty:

        missing_summary = missing_summary.sort_values(
            "missing_count",
            ascending=False
        )

    missing_summary.to_csv(
        MISSING_VALUES_FILE,
        index=False
    )

    # --------------------------------------------------------
    # Summary statistics
    # --------------------------------------------------------

    valid_times = parsed_time.dropna()

    content_lengths = cleaned["content_length_chars"]
    word_counts = cleaned["content_word_count"]

    unique_posts = df.loc[
        ~missing_id,
        "id"
    ].nunique()

    valid_authors = df.loc[
        ~missing_author,
        "author_id"
    ].nunique()

    report = [
        "MOLTBOOK DATA QUALITY REPORT",
        "============================",
        "",
        "A. DATASET OVERVIEW",
        f"Input records: {initial_count}",
        f"Valid object records: {initial_valid_count}",
        f"Malformed non-object records: {malformed_count}",
        f"Unique post IDs: {unique_posts}",
        f"Unique non-missing author IDs: {valid_authors}",
        "",
        "B. MISSING VALUES",
        f"Missing post IDs: {int(missing_id.sum())}",
        f"Missing titles: {int(missing_title.sum())}",
        f"Missing content: {int(missing_content.sum())}",
        f"Missing author IDs: {int(missing_author.sum())}",
        "",
        "C. DUPLICATES",
        f"Repeated post IDs after first occurrence: {int(duplicate_id.sum())}",
        f"Exact duplicate records: {int(exact_duplicate.sum())}",
        "",
        "D. TIMESTAMPS",
        f"Invalid or missing timestamps: {int(invalid_timestamp.sum())}",
        f"Earliest valid timestamp (UTC): "
        f"{valid_times.min() if not valid_times.empty else 'Unavailable'}",
        f"Latest valid timestamp (UTC): "
        f"{valid_times.max() if not valid_times.empty else 'Unavailable'}",
        "",
        "E. TEXT STATISTICS (CLEANED OUTPUT)",
        f"Empty content records: {int(cleaned['empty_content'].sum())}",
        (
            f"Average content length (characters): "
            f"{content_lengths.mean():.2f}"
            if len(content_lengths)
            else "Average content length: unavailable"
        ),
        (
            f"Median content length (characters): "
            f"{content_lengths.median():.2f}"
            if len(content_lengths)
            else "Median content length: unavailable"
        ),
        (
            f"Maximum content length (characters): "
            f"{content_lengths.max()}"
            if len(content_lengths)
            else "Maximum content length: unavailable"
        ),
        (
            f"Average content word count: "
            f"{word_counts.mean():.2f}"
            if len(word_counts)
            else "Average content word count: unavailable"
        ),
        "",
        "F. MODERATION FLAGS"
    ]

    for field in ["is_deleted", "is_spam"]:

        flag_field = f"{field}_flag"

        if flag_field in df.columns:

            report.append(
                f"Records marked {field}: "
                f"{int(df[flag_field].sum())}"
            )

        else:

            report.append(
                f"{field} field: not available"
            )

    report.extend([
        "",
        "G. CLEANING SUMMARY",
        f"Cleaned output records: {len(cleaned)}",
        f"Excluded records: {initial_count - len(cleaned)}",
        "Exclusion rule: missing post ID or repeated post ID.",
        "Other quality issues are flagged rather than automatically removed.",
        "",
        "H. OUTPUT FILES",
        str(CLEANED_POSTS_FILE),
        str(CLEANING_REPORT_FILE),
        str(MISSING_VALUES_FILE),
        "",
        "I. RESEARCH LIMITATIONS",
        "These checks do not establish whether posts were written by humans",
        "or AI agents. Account verification is not ground truth for authorship.",
        "Review flags and dataset limitations before modeling."
    ])

    CLEANING_REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8"
    )

    print("\n".join(report))

    print("\nCleaning completed.")
    print(f"Cleaned data: {CLEANED_POSTS_FILE}")
    print(f"Quality report: {CLEANING_REPORT_FILE}")
    print(f"Missing-value report: {MISSING_VALUES_FILE}")

    # ============================================================
# 7. MAIN PIPELINE
# ============================================================

def main():
    """Run the complete data collection and preprocessing pipeline."""

    RAW_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print("\n" + "=" * 65)
    print("MOLTBOOK DATA COLLECTION AND PREPROCESSING")
    print("=" * 65)

    print("\n[1/4] Collecting posts...")
    collect_posts()

    print("\n[2/4] Collecting comments...")
    collect_comments()

    print("\n[3/4] Extracting accounts...")
    extract_accounts()

    print("\n[4/4] Cleaning posts and generating quality reports...")
    clean_posts()

    print("\n" + "=" * 65)
    print("DATA COLLECTION AND PREPROCESSING PIPELINE FINISHED")
    print("=" * 65)


if __name__ == "__main__":
    main()