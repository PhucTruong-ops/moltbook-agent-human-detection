
import pandas as pd
import numpy as np
from pathlib import Path

INPUT_FILE = Path("data/processed/posts_cleaned.csv")
OUTPUT_DIR = Path("data/processed")
OUTPUT_FILE = OUTPUT_DIR / "posting_behavior_features.csv"

# Load data
df = pd.read_csv(INPUT_FILE)

# Parse timestamps consistently in UTC
df["created_at"] = pd.to_datetime(
    df["created_at"],
    utc=True,
    errors="coerce"
)

# Remove records that cannot be assigned to an account
# or used for time-based behavior analysis
df = df.dropna(subset=["author_id", "created_at"]).copy()

df = df.sort_values(["author_id", "created_at"])

# Extract temporal information
df["hour_utc"] = df["created_at"].dt.hour
df["date_utc"] = df["created_at"].dt.date

# Calculate intervals between consecutive posts
df["interval_minutes"] = (
    df.groupby("author_id")["created_at"]
    .diff()
    .dt.total_seconds() / 60
)

# Define nighttime as 00:00–05:59 UTC
df["is_night"] = df["hour_utc"].between(0, 5)

# Calculate account-level features
features = []

for account_id, group in df.groupby("author_id"):

    intervals = group["interval_minutes"].dropna()

    total_posts = len(group)
    active_days = group["date_utc"].nunique()

    avg_interval = intervals.mean()
    median_interval = intervals.median()
    interval_std = intervals.std()

    # Coefficient of variation
    if pd.notna(avg_interval) and avg_interval > 0:
        interval_cv = interval_std / avg_interval
    else:
        interval_cv = np.nan

    features.append({
        "author_id": account_id,
        "total_posts": total_posts,
        "first_post": group["created_at"].min(),
        "last_post": group["created_at"].max(),
        "active_days": active_days,
        "posts_per_active_day": total_posts / active_days,
        "avg_interval_minutes": avg_interval,
        "median_interval_minutes": median_interval,
        "interval_std_minutes": interval_std,
        "interval_cv": interval_cv,
        "burst_interval_pct": (
            (intervals <= 10).mean() * 100
            if len(intervals) > 0 else np.nan
        ),
        "night_post_pct": group["is_night"].mean() * 100,
        "unique_active_hours": group["hour_utc"].nunique(),
        "interval_count": len(intervals)
    })

result = pd.DataFrame(features)

# Save results
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
result.to_csv(OUTPUT_FILE, index=False)

print("=" * 50)
print("POSTING BEHAVIOR FEATURE EXTRACTION")
print("=" * 50)

print(f"Posts analyzed: {len(df):,}")
print(f"Accounts analyzed: {len(result):,}")
print(f"Accounts with 5+ posts: {(result['total_posts'] >= 5).sum():,}")
print(f"Accounts with 10+ posts: {(result['total_posts'] >= 10).sum():,}")
print(f"Accounts with at least 2 intervals: {(result['interval_count'] >= 2).sum():,}")

print(f"\nSaved features to: {OUTPUT_FILE}")

print("\nFeature preview:")
print(result.head(10).to_string(index=False))
