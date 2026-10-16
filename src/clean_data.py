
import json
from pathlib import Path

import pandas as pd

INPUT_FILE = Path("data/raw/posts.json")
OUTPUT_DIR = Path("data/processed")
OUTPUT_FILE = OUTPUT_DIR / "posts_cleaned.csv"
REPORT_FILE = OUTPUT_DIR / "cleaning_report.txt"


def clean_posts():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input file not found: {INPUT_FILE}. "
            "Run collect_data.py first."
        )

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError("Expected posts.json to contain a list of posts.")

    df = pd.DataFrame(records)
    initial_count = len(df)

    if df.empty:
        print("No posts found. Nothing to clean.")
        return

    # Record data-quality issues before modifying records.
    missing_id = df["id"].isna() | (
        df["id"].astype("string").str.strip() == ""
    )

    duplicate_id = (
        df["id"].notna()
        & df["id"].duplicated(keep="first")
    )

    missing_title = (
        df["title"].isna()
        | (df["title"].astype("string").str.strip() == "")
    ) if "title" in df.columns else pd.Series(
        True, index=df.index
    )

    missing_content = (
        df["content"].isna()
        | (df["content"].astype("string").str.strip() == "")
    ) if "content" in df.columns else pd.Series(
        True, index=df.index
    )

    if "created_at" in df.columns:
        parsed_time = pd.to_datetime(
            df["created_at"], errors="coerce", utc=True
        )
        invalid_timestamp = parsed_time.isna()
        df["created_at"] = parsed_time
    else:
        invalid_timestamp = pd.Series(True, index=df.index)

    # Preserve records and add explicit quality flags.
    df["missing_id"] = missing_id
    df["duplicate_id"] = duplicate_id
    df["missing_title"] = missing_title
    df["missing_content"] = missing_content
    df["invalid_timestamp"] = invalid_timestamp

    for field in ["is_deleted", "is_spam"]:
        if field in df.columns:
            df[f"{field}_flag"] = (
                df[field].fillna(False).astype(bool)
            )

    # Exclude only records without an identifiable post ID.
    # Other quality issues remain available for analysis.
    cleaned = df.loc[~missing_id & ~duplicate_id].copy()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(OUTPUT_FILE, index=False)

    report = [
        "Moltbook Data Cleaning Report",
        "==============================",
        f"Input records: {initial_count}",
        f"Missing IDs: {int(missing_id.sum())}",
        f"Duplicate IDs: {int(duplicate_id.sum())}",
        f"Missing titles: {int(missing_title.sum())}",
        f"Missing content: {int(missing_content.sum())}",
        f"Invalid timestamps: {int(invalid_timestamp.sum())}",
        f"Output records: {len(cleaned)}",
        f"Excluded records: {initial_count - len(cleaned)}",
    ]

    if "is_deleted" in df.columns:
        report.append(
            f"Deleted-marked records: "
            f"{int(df['is_deleted'].fillna(False).astype(bool).sum())}"
        )

    if "is_spam" in df.columns:
        report.append(
            f"Spam-marked records: "
            f"{int(df['is_spam'].fillna(False).astype(bool).sum())}"
        )

    REPORT_FILE.write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )

    print("\n".join(report))
    print(f"\nCleaned data saved to: {OUTPUT_FILE}")
    print(f"Report saved to: {REPORT_FILE}")


if __name__ == "__main__":
    clean_posts()
