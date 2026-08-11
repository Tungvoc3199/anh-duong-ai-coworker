from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only smoke check for Async Task Runner v1."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8790",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get(
            "ANH_DUONG_INTERNAL_API_TOKEN"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        print(
            "ERROR: set ANH_DUONG_INTERNAL_API_TOKEN "
            "or pass --token.",
            file=sys.stderr,
        )
        return 2

    headers = {
        "Authorization": f"Bearer {args.token}",
    }
    try:
        with httpx.Client(
            base_url=args.base_url.rstrip("/"),
            timeout=args.timeout,
        ) as client:
            health = client.get("/health")
            health.raise_for_status()
            runs = client.get(
                "/api/async-tasks",
                headers=headers,
                params={"limit": 1},
            )
            runs.raise_for_status()
    except httpx.HTTPError as error:
        print(
            f"SMOKE_FAILED={type(error).__name__}",
            file=sys.stderr,
        )
        return 1

    health_body: Any = health.json()
    runs_body: Any = runs.json()
    if not isinstance(health_body, dict):
        print("SMOKE_FAILED=invalid_health", file=sys.stderr)
        return 1
    if not isinstance(runs_body, list):
        print("SMOKE_FAILED=invalid_async_list", file=sys.stderr)
        return 1

    print("SMOKE_OK=true")
    print(f"service_status={health_body.get('status')}")
    print(f"sampled_runs={len(runs_body)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

