
import pandas as pd

FILE_PATH = "data/processed/posts_cleaned.csv"

df = pd.read_csv(FILE_PATH)

# Parse timestamps
df["created_at"] = pd.to_datetime(
    df["created_at"],
    utc=True,
    errors="coerce"
)

print("=" * 50)
print("POSTING DATASET OVERVIEW")
print("=" * 50)

print(f"Total posts: {len(df):,}")
print(f"Unique post IDs: {df['id'].nunique():,}")
print(f"Unique accounts: {df['author_id'].nunique():,}")

print("\n--- TIMESTAMP INFORMATION ---")

print("Earliest post:", df["created_at"].min())
print("Latest post:", df["created_at"].max())

print("Missing timestamps:", df["created_at"].isna().sum())

print("\n--- DATA QUALITY ---")

print("Missing author IDs:", df["author_id"].isna().sum())
print("Duplicate post IDs:", df["id"].duplicated().sum())
print("Invalid timestamps:", df["invalid_timestamp"].sum())
print("Deleted posts:", df["is_deleted"].sum())
print("Spam posts:", df["is_spam"].sum())
print("Empty content:", df["empty_content"].sum())

print("\n--- POSTS PER ACCOUNT ---")

posts_per_account = df.groupby("author_id").size()

print(posts_per_account.describe())

print("\n--- TOP 10 MOST ACTIVE ACCOUNTS ---")

print(posts_per_account.nlargest(10))

print("\n--- POSTS BY MONTH ---")

print(
    df.groupby(df["created_at"].dt.to_period("M"))
    .size()
)
