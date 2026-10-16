
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

    print("\nResponse keys:", list(data.keys()))
    print("\nSample response:")
    print(data)

except requests.RequestException as error:
    print("API request failed:", error)
except ValueError:
    print("The response was not valid JSON.")
