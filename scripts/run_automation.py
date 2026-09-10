import argparse
import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))


def get_configured_automation_key() -> str:
    """Read AUTOMATION_API_KEY from environment or repo .env file directly."""
    env_val = os.environ.get("AUTOMATION_API_KEY")
    if env_val:
        return env_val
    env_file = repo_root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("AUTOMATION_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def run_job(job_name: str, base_url: str, api_key: str, notify_telegram: bool = True) -> dict:
    if job_name == "backup":
        print("Triggering [BACKUP] routine...")
        import subprocess
        python_exe = sys.executable
        res = subprocess.run([python_exe, "-m", "scripts.backup"], cwd=str(repo_root), capture_output=True, text=True)
        if res.returncode != 0:
            print(f"❌ [BACKUP] Failed: {res.stderr}")
            raise RuntimeError(res.stderr)
        print(f"✅ [BACKUP] Success:\n{res.stdout.strip()}")
        if notify_telegram:
            try:
                from src.app.core.config import settings
                from src.app.integrations.telegram.service import TelegramService
                import asyncio
                if settings.telegram_allowed_user_ids:
                    ts = TelegramService()
                    user_id = int(list(settings.telegram_allowed_user_ids)[0])
                    asyncio.run(ts.send_message(
                        chat_id=user_id,
                        text=f"🛡️ **Backup de Siguranță Finalizat cu Succes!**\n\n{res.stdout.strip()}\nDump PostgreSQL și Snapshot Qdrant verificate criptografic SHA256."
                    ))
            except Exception as e:
                print(f"Warning: Could not send Telegram backup alert: {e}")
        return {"status": "success", "detail": res.stdout.strip()}

    endpoints = {
        "deadlines": ("/api/v1/automation/practice/deadlines-check", {"notify_telegram": str(notify_telegram).lower()}),
        "briefing": ("/api/v1/automation/daily-briefing", {"notify_telegram": str(notify_telegram).lower()}),
        "news": ("/api/v1/automation/news/refresh", {}),
        "email": ("/api/v1/automation/email/poll", {"notify_telegram": str(notify_telegram).lower()}),
    }

    if job_name not in endpoints:
        raise ValueError(f"Unknown job '{job_name}'. Available: {list(endpoints.keys()) + ['backup']}")

    endpoint, params = endpoints[job_name]
    query_string = urllib.parse.urlencode(params)
    full_url = f"{base_url.rstrip('/')}{endpoint}"
    if query_string:
        full_url = f"{full_url}?{query_string}"

    print(f"Triggering [{job_name.upper()}] via {full_url}...")

    req = urllib.request.Request(
        full_url,
        data=b"",
        headers={"X-Automation-Key": api_key},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"✅ [{job_name.upper()}] Success:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return data
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8")
        print(f"❌ [{job_name.upper()}] Failed with HTTP {exc.code}: {err_body}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Trigger academic assistant automation jobs.")
    parser.add_argument(
        "--job",
        choices=["deadlines", "briefing", "news", "email", "backup", "all"],
        default="deadlines",
        help="Automation job to trigger (default: deadlines)",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="FastAPI application base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Automation secret key (defaults to AUTOMATION_API_KEY in .env)",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Disable sending proactive Telegram messages",
    )
    args = parser.parse_args()

    key = args.api_key or get_configured_automation_key()
    if not key:
        print("Error: AUTOMATION_API_KEY is not configured in .env and was not provided via --api-key.")
        sys.exit(1)

    notify = not args.no_telegram
    jobs = ["deadlines", "briefing", "news", "email"] if args.job == "all" else [args.job]

    for job in jobs:
        try:
            run_job(job, args.base_url, key, notify_telegram=notify)
        except Exception as e:
            print(f"Job {job} failed: {e}")
            if args.job != "all":
                sys.exit(1)


if __name__ == "__main__":
    main()
