from __future__ import annotations

import argparse
import os

import uvicorn

from .api import app, manager, settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Certificate auto issue/renew API")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="run api server")
    subparsers.add_parser("check-renew", help="check expiry and renew when needed")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "serve":
        uvicorn.run(app, host=settings.api_host, port=settings.api_port)
        return

    result = manager.run_check_and_renew_job(
        lock_already_held=os.getenv("CERT_AUTO_API_LOCK_OWNED") == "1"
    )
    print(result)


if __name__ == "__main__":
    main()
