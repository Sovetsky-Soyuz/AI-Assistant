from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.config import load_dotenv


def main() -> int:
    root_dir = Path(__file__).resolve().parent
    load_dotenv(root_dir / ".env")

    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    port = int(os.getenv("ASSISTANT_PORT", "8000"))

    if not admin_token:
        print("ADMIN_TOKEN is not configured in .env.")
        return 1

    url = f"http://127.0.0.1:{port}/api/admin/flush"
    request = Request(
        url,
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Admin-Token": admin_token,
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
            data = json.loads(payload) if payload else {}
            print(json.dumps(data, indent=2))
            return 0
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        if payload:
            print(payload)
        else:
            print(f"HTTP {exc.code}: {exc.reason}")
        return 1
    except URLError as exc:
        print(f"Could not reach the Orbit server: {exc.reason}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
