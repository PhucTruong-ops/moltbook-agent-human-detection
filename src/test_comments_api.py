
import requests

BASE_URL = "https://www.moltbook.com/api/v1"

post_id = "d2cdb167-7829-4c0a-9913-e4062dac8b31"

url = f"{BASE_URL}/posts/{post_id}/comments"

params = {
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

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                print(f"\n{key}: {len(value)} records")

                if value and isinstance(value[0], dict):
                    print("First comment fields:", list(value[0].keys()))

            elif isinstance(value, dict):
                print(f"\n{key}: dictionary")
                print("Fields:", list(value.keys()))

            else:
                print(f"{key}: {value}")
    else:
        print("Response type:", type(data).__name__)

except requests.RequestException as error:
    print("API request failed:", error)

except ValueError:
    print("The response was not valid JSON.")
