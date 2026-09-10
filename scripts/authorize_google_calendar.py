"""Run a one-time local OAuth authorization flow for Google Calendar."""

import argparse
from pathlib import Path

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize Google Calendar OAuth and save a refreshable token.")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the authorization URL.")
    args = parser.parse_args()

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise ConfigurationException("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env before authorizing.")
    if "your-google" in settings.GOOGLE_CLIENT_ID or "your-google" in settings.GOOGLE_CLIENT_SECRET:
        raise ConfigurationException("Google OAuth credentials still contain example placeholders.")
    if settings.GOOGLE_AUTH_MODE.lower() != "oauth":
        raise ConfigurationException("Set GOOGLE_AUTH_MODE=oauth to use this authorization script.")

    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, settings.google_calendar_scopes)
    credentials = flow.run_local_server(port=0, open_browser=not args.no_browser)
    token_path = Path(settings.GOOGLE_TOKEN_FILE)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Google Calendar OAuth token saved to {token_path}")


if __name__ == "__main__":
    main()
