import argparse
import json
from json import JSONDecodeError
import sys

import httpx


DEFAULT_API = "http://127.0.0.1:8000"


def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2))


def _handle_error(response: httpx.Response) -> int:
    try:
        payload = response.json()
    except JSONDecodeError:
        payload = {"error": response.text}
    _print_json({"status_code": response.status_code, "response": payload})
    return 1


def cmd_publish(args) -> int:
    tags = [value.strip() for value in args.tags.split(",") if value.strip()]
    payload = {"title": args.title, "text": args.text, "tags": tags}
    response = httpx.post(f"{args.api}/api/publish", json=payload, timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    _print_json(response.json())
    return 0


def cmd_get(args) -> int:
    response = httpx.get(
        f"{args.api}/api/get/{args.root_hash}",
        params={"device_id": args.device_id},
        timeout=10,
    )
    if response.status_code >= 400:
        return _handle_error(response)
    _print_json(response.json())
    return 0


def cmd_earn(args) -> int:
    payload = {"device_id": args.device_id, "task_id": args.task_id}
    response = httpx.post(f"{args.api}/api/earn", json=payload, timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    _print_json(response.json())
    return 0


def cmd_search(args) -> int:
    params = {"tag": args.tag} if args.tag else None
    response = httpx.get(f"{args.api}/api/content", params=params, timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    _print_json(response.json())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tfp", description="TFP demo CLI")
    parser.add_argument("--api", default=DEFAULT_API, help="TFP demo API base URL")

    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish", help="Publish text content")
    publish.add_argument("--title", required=True, help="Content title")
    publish.add_argument("--text", required=True, help="Content body text")
    publish.add_argument("--tags", default="", help="Comma-separated tags")
    publish.set_defaults(func=cmd_publish)

    get = sub.add_parser("get", help="Fetch content by root hash")
    get.add_argument("root_hash", help="Content root hash")
    get.add_argument("--device-id", default="cli-user", help="Device id for credit accounting")
    get.set_defaults(func=cmd_get)

    earn = sub.add_parser("earn", help="Earn credits by submitting compute task")
    earn.add_argument("--task-id", required=True, help="Task recipe identifier")
    earn.add_argument("--device-id", default="cli-user", help="Device id for credit accounting")
    earn.set_defaults(func=cmd_earn)

    search = sub.add_parser("search", help="List published content")
    search.add_argument("--tag", help="Filter by tag")
    search.set_defaults(func=cmd_search)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except httpx.RequestError as exc:
        _print_json({"error": "failed to reach API", "detail": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
