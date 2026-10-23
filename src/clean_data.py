
import json
from pathlib import Path

import pandas as pd

INPUT_FILE = Path("data/raw/posts.json")
OUTPUT_DIR = Path("data/processed")
OUTPUT_FILE = OUTPUT_DIR / "posts_cleaned.csv"
REPORT_FILE = OUTPUT_DIR / "cleaning_report.txt"
MISSING_FILE = OUTPUT_DIR / "missing_values_by_field.csv"


def is_missing(series):
    """Treat nulls and blank strings as missing."""
    return (
        series.isna()
        | series.astype("string").str.strip().eq("").fillna(False)
    )


def parse_boolean(value):
    """Convert common API boolean representations safely."""
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


def clean_posts():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}. "
            "Run collect_data.py first."
        )

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError("Expected posts.json to contain a list.")

    # Keep only dictionary-shaped records for tabular processing.
    valid_records = [r for r in records if isinstance(r, dict)]
    malformed_records = len(records) - len(valid_records)

    df = pd.DataFrame(valid_records)
    initial_count = len(records)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if df.empty:
        REPORT_FILE.write_text(
            "Moltbook Data Quality Report\n"
            "============================\n"
            f"Input records: {initial_count}\n"
            f"Malformed non-object records: {malformed_records}\n"
            "No valid post objects were available for analysis.\n",
            encoding="utf-8",
        )
        print(f"No valid post objects. Report saved to {REPORT_FILE}")
        return

    # Add expected columns if the API omitted them entirely.
    for field in ["id", "title", "content", "author_id", "created_at"]:
        if field not in df.columns:
            df[field] = pd.NA

    # Normalize blank identifiers before checking duplicates.
    df["id"] = df["id"].astype("string").str.strip()
    missing_id = is_missing(df["id"])

    # Count all occurrences after the first for repeated non-empty IDs.
    duplicate_id = (
        df["id"].notna()
        & df["id"].ne("")
        & df["id"].duplicated(keep="first")
    )

    missing_title = is_missing(df["title"])
    missing_content = is_missing(df["content"])
    missing_author = is_missing(df["author_id"])

    # Parse timestamps as UTC. Invalid values become NaT.
    parsed_time = pd.to_datetime(
        df["created_at"], errors="coerce", utc=True
    )
    invalid_timestamp = parsed_time.isna()
    df["created_at"] = parsed_time

    # Add explicit quality flags to each record.
    df["missing_id"] = missing_id
    df["duplicate_id"] = duplicate_id
    df["missing_title"] = missing_title
    df["missing_content"] = missing_content
    df["missing_author_id"] = missing_author
    df["invalid_timestamp"] = invalid_timestamp

    # Parse moderation/status fields without treating "false" as True.
    for field in ["is_deleted", "is_spam"]:
        if field in df.columns:
            df[f"{field}_flag"] = df[field].map(parse_boolean)

    # Text metrics are descriptive features, not quality judgments.
    title_text = df["title"].fillna("").astype(str)
    content_text = df["content"].fillna("").astype(str)

    df["title_length_chars"] = title_text.str.len()
    df["content_length_chars"] = content_text.str.len()
    df["content_word_count"] = content_text.str.split().str.len()

    # Identify exact duplicate records separately from duplicate IDs.
    exact_duplicate = df.duplicated(keep="first")
    df["exact_duplicate_record"] = exact_duplicate

    # Exclude records that cannot be identified or duplicate an earlier ID.
    # Preserve other quality issues as flags for later analysis.
    keep = ~missing_id & ~duplicate_id
    cleaned = df.loc[keep].copy()

    # Export cleaned records. Raw JSON is not changed.
    cleaned.to_csv(OUTPUT_FILE, index=False)

    # Missing-value summary across the original valid post objects.
    missing_summary = pd.DataFrame({
        "field": df.columns,
        "missing_count": [
            int(is_missing(df[col]).sum()) for col in df.columns
        ],
    })
    missing_summary["missing_percent"] = (
        missing_summary["missing_count"] / len(df) * 100
    ).round(2)

    missing_summary.sort_values(
        "missing_count", ascending=False
    ).to_csv(MISSING_FILE, index=False)

    # Descriptive statistics for valid timestamps and text.
    valid_times = parsed_time.dropna()
    valid_lengths = cleaned["content_length_chars"]

    report = [
        "Moltbook Data Quality Report",
        "============================",
        "",
        "DATASET COUNTS",
        f"Input records in JSON: {initial_count}",
        f"Valid object records: {len(df)}",
        f"Malformed non-object records: {malformed_records}",
        f"Missing IDs: {int(missing_id.sum())}",
        f"Repeated IDs after first occurrence: {int(duplicate_id.sum())}",
        f"Exact duplicate records: {int(exact_duplicate.sum())}",
        f"Missing titles: {int(missing_title.sum())}",
        f"Missing content: {int(missing_content.sum())}",
        f"Missing author IDs: {int(missing_author.sum())}",
        f"Invalid or missing timestamps: {int(invalid_timestamp.sum())}",
        f"Cleaned output records: {len(cleaned)}",
        f"Records excluded from cleaned output: {initial_count - len(cleaned)}",
        "",
        "COVERAGE",
        f"Unique post IDs in input: {df.loc[~missing_id, 'id'].nunique()}",
        f"Unique authors among non-missing author IDs: "
        f"{df.loc[~missing_author, 'author_id'].nunique()}",
        "",
        "TIMESTAMP RANGE (UTC)",
        f"Earliest valid timestamp: "
        f"{valid_times.min() if not valid_times.empty else 'Unavailable'}",
        f"Latest valid timestamp: "
        f"{valid_times.max() if not valid_times.empty else 'Unavailable'}",
        "",
        "CONTENT LENGTH (characters, cleaned output)",
        f"Mean: {valid_lengths.mean():.2f}" if len(valid_lengths) else "Mean: unavailable",
        f"Median: {valid_lengths.median():.2f}" if len(valid_lengths) else "Median: unavailable",
        f"Minimum: {valid_lengths.min()}" if len(valid_lengths) else "Minimum: unavailable",
        f"Maximum: {valid_lengths.max()}" if len(valid_lengths) else "Maximum: unavailable",
        "",
        "OUTPUT FILES",
        str(OUTPUT_FILE),
        str(REPORT_FILE),
        str(MISSING_FILE),
        "",
        "NOTE",
        "Quality flags describe detected issues; they do not prove that "
        "a post is authentic, human-authored, or AI-authored.",
        "This report covers the checks implemented here, not every possible "
        "data-quality or research-validity issue.",
    ]

    for field in ["is_deleted", "is_spam"]:
        flag = f"{field}_flag"
        if flag in df.columns:
            report.insert(
                report.index("COVERAGE"),
                f"Records marked {field}: {int(df[flag].sum())}",
            )

    REPORT_FILE.write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )

    print("\n".join(report))
    print(f"\nSaved cleaned data: {OUTPUT_FILE}")
    print(f"Saved quality report: {REPORT_FILE}")
    print(f"Saved missing-value summary: {MISSING_FILE}")


if __name__ == "__main__":
    clean_posts()