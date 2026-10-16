
import requests

BASE_URL = "https://www.moltbook.com/api/v1"

# Use an author name from your collected posts.
agent_name = "obviouslylyn ot"

url = f"{BASE_URL}/agents/profile"

params = {
    "name": agent_name
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
            if isinstance(value, dict):
                print(f"{key}: dictionary")
                print("Fields:", list(value.keys()))

            elif isinstance(value, list):
                print(f"{key}: {len(value)} records")

                if value and isinstance(value[0], dict):
                    print("First record fields:",
                          list(value[0].keys()))

            else:
                print(f"{key}: {value}")
    else:
        print("Response type:", type(data).__name__)

except requests.RequestException as error:
    print("API request failed:", error)

except ValueError:
    print("The response was not valid JSON.")
