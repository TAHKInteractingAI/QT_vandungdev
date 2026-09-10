"""
Google OAuth 2.0 Desktop Authentication Script.
Runs a local server to complete the user authorization flow and generates `token.json`.
"""

import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CLIENT_SECRET_FILE = Path("client_secret.json")
TOKEN_FILE = Path("token.json")


def authenticate() -> None:
    if not CLIENT_SECRET_FILE.exists():
        print(f"Error: {CLIENT_SECRET_FILE} not found in current directory.", file=sys.stderr, flush=True)
        sys.exit(1)

    print("\nStarting local authentication server...", flush=True)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE),
        scopes=SCOPES,
    )

    # run_local_server on fixed port 8085 with standard state handling
    creds = flow.run_local_server(
        port=8085,
        prompt="consent",
        access_type="offline",
        open_browser=True,
    )

    # Save credentials to token.json
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"\nAUTH_SUCCESS: Credentials saved to {TOKEN_FILE.resolve()}", flush=True)


if __name__ == "__main__":
    authenticate()
