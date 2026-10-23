
import json
from pathlib import Path

import pandas as pd


# --------------------------------------------------
# Configuration
# --------------------------------------------------

INPUT_FILE = Path("data/raw/posts.json")
OUTPUT_DIR = Path("data/processed")

OUTPUT_FILE = OUTPUT_DIR / "posts_cleaned.csv"
REPORT_FILE = OUTPUT_DIR / "cleaning_report.txt"
MISSING_FILE = OUTPUT_DIR / "missing_values_by_field.csv"


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

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
        default=str,
    )


# --------------------------------------------------
# Main cleaning function
# --------------------------------------------------

def clean_posts():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}. "
            "Run src/collect_data.py first."
        )

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError(
            "Expected posts.json to contain a JSON list."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    initial_count = len(records)

    # Preserve dictionary-shaped post records for analysis.
    valid_records = [
        record for record in records
        if isinstance(record, dict)
    ]

    malformed_count = initial_count - len(valid_records)

    if not valid_records:
        report = [
            "Moltbook Data Quality Report",
            "============================",
            f"Input records: {initial_count}",
            f"Malformed non-object records: {malformed_count}",
            "No valid post objects were available for analysis.",
        ]

        REPORT_FILE.write_text(
            "\n".join(report) + "\n",
            encoding="utf-8",
        )

        print("\n".join(report))
        return

    # Save the original field structure before adding quality flags.
    original_fields = sorted({
        field
        for record in valid_records
        for field in record.keys()
    })

    df = pd.DataFrame(valid_records)
    initial_valid_count = len(df)

    # Add expected fields if absent from the API response.
    required_fields = [
        "id",
        "title",
        "content",
        "author_id",
        "created_at",
    ]

    for field in required_fields:
        if field not in df.columns:
            df[field] = pd.NA

    # ----------------------------------------------
    # 1. Missing values
    # ----------------------------------------------

    df["id"] = df["id"].astype("string").str.strip()

    missing_id = is_missing(df["id"])
    missing_title = is_missing(df["title"])
    missing_content = is_missing(df["content"])
    missing_author = is_missing(df["author_id"])

    # ----------------------------------------------
    # 2. Duplicate IDs and duplicate records
    # ----------------------------------------------

    duplicate_id = (
        df["id"].notna()
        & df["id"].ne("")
        & df["id"].duplicated(keep="first")
    )

    fingerprints = pd.Series(
        [record_fingerprint(record) for record in valid_records],
        index=df.index,
        dtype="string",
    )

    exact_duplicate = fingerprints.duplicated(keep="first")

    # ----------------------------------------------
    # 3. Timestamp validation
    # ----------------------------------------------

    parsed_time = pd.to_datetime(
        df["created_at"],
        errors="coerce",
        utc=True,
    )

    invalid_timestamp = parsed_time.isna()

    df["created_at"] = parsed_time

    # ----------------------------------------------
    # 4. Add quality flags
    # ----------------------------------------------

    df["missing_id"] = missing_id
    df["duplicate_id"] = duplicate_id
    df["exact_duplicate_record"] = exact_duplicate
    df["missing_title"] = missing_title
    df["missing_content"] = missing_content
    df["missing_author_id"] = missing_author
    df["invalid_timestamp"] = invalid_timestamp

    for field in ["is_deleted", "is_spam"]:
        if field in df.columns:
            df[f"{field}_flag"] = df[field].map(parse_boolean)

    # ----------------------------------------------
    # 5. Text statistics
    # ----------------------------------------------

    title_text = df["title"].fillna("").astype(str)
    content_text = df["content"].fillna("").astype(str)

    df["title_length_chars"] = title_text.str.len()
    df["content_length_chars"] = content_text.str.len()
    df["content_word_count"] = content_text.str.split().str.len()

    # Flag empty or whitespace-only content.
    df["empty_content"] = content_text.str.strip().eq("")

    # ----------------------------------------------
    # 6. Determine cleaned output
    # ----------------------------------------------

    # Exclude missing IDs and repeated IDs after the first occurrence.
    # Preserve other quality issues as flags for further investigation.
    keep = ~missing_id & ~duplicate_id
    cleaned = df.loc[keep].copy()

    cleaned.to_csv(OUTPUT_FILE, index=False)

    # ----------------------------------------------
    # 7. Missing-value summary by original field
    # ----------------------------------------------

    missing_rows = []

    for field in original_fields:
        if field in df.columns:
            missing_count = int(is_missing(df[field]).sum())
        else:
            missing_count = len(df)

        missing_rows.append({
            "field": field,
            "missing_count": missing_count,
            "missing_percent": round(
                missing_count / initial_valid_count * 100, 2
            ) if initial_valid_count else 0,
        })

    missing_summary = pd.DataFrame(missing_rows)

    if not missing_summary.empty:
        missing_summary = missing_summary.sort_values(
            "missing_count",
            ascending=False,
        )

    missing_summary.to_csv(MISSING_FILE, index=False)

    # ----------------------------------------------
    # 8. Descriptive statistics
    # ----------------------------------------------

    valid_times = parsed_time.dropna()
    content_lengths = cleaned["content_length_chars"]
    word_counts = cleaned["content_word_count"]

    unique_posts = df.loc[
        ~missing_id, "id"
    ].nunique()

    valid_authors = df.loc[
        ~missing_author, "author_id"
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
        f"Repeated post IDs after first occurrence: "
        f"{int(duplicate_id.sum())}",
        f"Exact duplicate records: {int(exact_duplicate.sum())}",
        "",
        "D. TIMESTAMPS",
        f"Invalid or missing timestamps: "
        f"{int(invalid_timestamp.sum())}",
        f"Earliest valid timestamp (UTC): "
        f"{valid_times.min() if not valid_times.empty else 'Unavailable'}",
        f"Latest valid timestamp (UTC): "
        f"{valid_times.max() if not valid_times.empty else 'Unavailable'}",
        "",
        "E. TEXT STATISTICS (CLEANED OUTPUT)",
        f"Empty content records: "
        f"{int(cleaned['empty_content'].sum())}",
        f"Average content length (characters): "
        f"{content_lengths.mean():.2f}" if len(content_lengths)
        else "Average content length: unavailable",
        f"Median content length (characters): "
        f"{content_lengths.median():.2f}" if len(content_lengths)
        else "Median content length: unavailable",
        f"Maximum content length (characters): "
        f"{content_lengths.max()}" if len(content_lengths)
        else "Maximum content length: unavailable",
        f"Average content word count: "
        f"{word_counts.mean():.2f}" if len(word_counts)
        else "Average content word count: unavailable",
        "",
        "F. MODERATION FLAGS",
    ]

    for field in ["is_deleted", "is_spam"]:
        flag_field = f"{field}_flag"

        if flag_field in df.columns:
            report.append(
                f"Records marked {field}: {int(df[flag_field].sum())}"
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
        str(OUTPUT_FILE),
        str(REPORT_FILE),
        str(MISSING_FILE),
        "",
        "I. RESEARCH LIMITATIONS",
        "These checks do not establish whether posts were written by humans",
        "or AI agents. Account verification is not ground truth for authorship.",
        "Review flags and dataset limitations before modeling.",
    ])

    REPORT_FILE.write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print("\n".join(report))
    print("\nCleaning completed.")
    print(f"Cleaned data: {OUTPUT_FILE}")
    print(f"Quality report: {REPORT_FILE}")
    print(f"Missing-value report: {MISSING_FILE}")


if __name__ == "__main__":
    clean_posts()
