
import requests

BASE_URL = "https://www.moltbook.com/api/v1"

url = f"{BASE_URL}/posts"

params = {
    "sort": "new",
    "limit": 5
}

try:
    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    print("Status code:", response.status_code)
    response.raise_for_status()

    data = response.json()

    print("\nResponse structure:")

    for key, value in data.items():
        if isinstance(value, list):
            print(f"\n{key}: {len(value)} records")

            if value and isinstance(value[0], dict):
                print("First record fields:", list(value[0].keys()))

        elif isinstance(value, dict):
            print(f"\n{key}: dictionary")
            print("Fields:", list(value.keys()))

        else:
            print(f"{key}: {value}")

except requests.RequestException as error:
    print("API request failed:", error)

except ValueError:
    print("The response was not valid JSON.")
