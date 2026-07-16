import json
import requests


def main():
    session = requests.Session()

    login_url = "http://localhost:8000/api/v1/auth/login"
    login_payload = {
        "identifier": "ashishjangde54@gmail.com",
        "password": "12345678@As",
    }

    print(f"Logging into {login_url}...")
    res = session.post(login_url, json=login_payload)
    if res.status_code != 200:
        print(f"Login failed: {res.status_code} {res.text}")
        return
    print("Login successful.")

    # Read the JSON artifact from the same directory as the script
    import os

    json_path = os.path.join(os.path.dirname(__file__), "multi_asset_strategy.json")
    with open(json_path, "r") as f:
        canvas_json = json.load(f)

    strategy_url = "http://localhost:8000/api/v1/strategies"
    strategy_payload = {
        "name": "Official Multi-Asset Trend & Momentum",
        "description": "The official flagship strategy from the CrypAlgos Strategy Builder Guide.",
        "canvas_json": canvas_json,
    }

    print(f"Creating strategy at {strategy_url}...")
    # Because auth tokens might be returned in the response as well as cookies, check for access_token header just in case.
    # The route returns HTTP-only cookies based on the comment `Sets HTTP-only cookies`.
    # Let's also attach the Bearer token just in case the backend requires it explicitly.
    try:
        access_token = res.json().get("data", {}).get("access_token")
    except:
        access_token = res.json().get("access_token")

    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    res = session.post(strategy_url, json=strategy_payload, headers=headers)
    if res.status_code in (200, 201):
        print(
            f"Strategy created successfully! ID: {res.json().get('data', {}).get('id', 'unknown')}"
        )
    else:
        print(f"Strategy creation failed: {res.status_code} {res.text}")


if __name__ == "__main__":
    main()
