import argparse
import datetime
import hashlib
import hmac as _hmac
import json
import os
import sys
import time
from json import JSONDecodeError

import httpx
from tfp_client.lib.compute.task_executor import TaskSpec, execute_task

try:
    from tfp_cli import identity as secure_identity
except Exception:  # pragma: no cover - optional dependency path
    secure_identity = None

DEFAULT_API = "http://127.0.0.1:8000"

# ---------------------------------------------------------------------------
# Device identity helpers (stored in ~/.tfp/identity.json)
# ---------------------------------------------------------------------------


def _identity_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".tfp", "identity.json")


def _legacy_load_or_create_identity(device_id: str) -> dict:
    """Load device identity or create a new one if not found."""
    path = _identity_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path) as f:
            identities = json.load(f)
        if device_id in identities:
            entry = identities[device_id]
            return {
                "device_id": device_id,
                "puf_entropy": bytes.fromhex(entry["puf_entropy_hex"]),
            }
    # Generate new identity
    puf_entropy = os.urandom(32)
    identities = {}
    if os.path.exists(path):
        with open(path) as f:
            identities = json.load(f)
    identities[device_id] = {"puf_entropy_hex": puf_entropy.hex()}
    with open(path, "w") as f:
        json.dump(identities, f, indent=2)
    return {"device_id": device_id, "puf_entropy": puf_entropy}


def _load_or_create_identity(
    device_id: str, passphrase: str | None = None, mnemonic: str | None = None
) -> dict:
    passphrase = passphrase or None
    mnemonic = mnemonic or None
    if passphrase:
        if secure_identity is None:
            raise RuntimeError(
                "Secure identity module unavailable; install security extras for encrypted identities."
            )
        return secure_identity.load_or_create_identity(
            device_id=device_id, passphrase=passphrase, mnemonic=mnemonic
        )
    return _legacy_load_or_create_identity(device_id)


def _make_sig(puf_entropy: bytes, message: str) -> str:
    return _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()


def _ensure_enrolled(api: str, device_id: str, puf_entropy: bytes) -> bool:
    """Enroll device if not already enrolled. Returns True on success."""
    resp = httpx.post(
        f"{api}/api/enroll",
        json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
        timeout=10,
    )
    return resp.status_code == 200


def _print_json(data: dict) -> None:
    print(json.dumps(data, indent=2))


def _handle_error(response: httpx.Response) -> int:
    try:
        payload = response.json()
    except JSONDecodeError:
        payload = {"error": response.text}
    _print_json({"status_code": response.status_code, "response": payload})
    return 1


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_publish(args) -> int:
    identity = _load_or_create_identity(
        args.device_id, args.identity_passphrase, args.identity_mnemonic
    )
    puf_entropy = identity["puf_entropy"]
    _ensure_enrolled(args.api, args.device_id, puf_entropy)
    tags = [value.strip() for value in args.tags.split(",") if value.strip()]
    payload = {
        "title": args.title,
        "text": args.text,
        "tags": tags,
        "device_id": args.device_id,
    }
    sig = _make_sig(puf_entropy, f"{args.device_id}:{args.title}")
    response = httpx.post(
        f"{args.api}/api/publish",
        json=payload,
        headers={"X-Device-Sig": sig},
        timeout=10,
    )
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
    identity = _load_or_create_identity(
        args.device_id, args.identity_passphrase, args.identity_mnemonic
    )
    puf_entropy = identity["puf_entropy"]
    _ensure_enrolled(args.api, args.device_id, puf_entropy)
    payload = {"device_id": args.device_id, "task_id": args.task_id}
    sig = _make_sig(puf_entropy, f"{args.device_id}:{args.task_id}")
    response = httpx.post(
        f"{args.api}/api/earn",
        json=payload,
        headers={"X-Device-Sig": sig},
        timeout=10,
    )
    if response.status_code >= 400:
        return _handle_error(response)
    _print_json(response.json())
    return 0


def cmd_search(args) -> int:
    """Search published content by tag(s) with optional pagination."""
    params: dict = {"limit": args.limit, "offset": args.offset}
    if args.tags:
        params["tags"] = args.tags
    elif args.tag:
        params["tag"] = args.tag
    response = httpx.get(f"{args.api}/api/content", params=params, timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    data = response.json()
    items = data.get("items", [])
    total = data.get("total", len(items))
    offset = data.get("offset", 0)
    if not items:
        print("No content found.")
        return 0
    print(f"Showing {len(items)} of {total} items (offset {offset}):")
    print(f"\n{'#':<4} {'ROOT_HASH':<18} {'TAGS':<30} TITLE")
    print("-" * 80)
    for i, item in enumerate(items, offset + 1):
        tags_str = ",".join(item.get("tags", []))[:28]
        hash_short = item.get("root_hash", "")[:16] + "…"
        title = item.get("title", "")[:40]
        print(f"{i:<4} {hash_short:<18} {tags_str:<30} {title}")
    if total > offset + len(items):
        print(f"\n  (more results — use --offset {offset + len(items)} to continue)")
    return 0


def cmd_tasks(args) -> int:
    """List open compute tasks from the node."""
    params = {"limit": args.limit}
    response = httpx.get(f"{args.api}/api/tasks", params=params, timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    data = response.json()
    tasks = data.get("tasks", [])
    if not tasks:
        print("No open tasks at the moment. Try again in a few seconds.")
        return 0
    print(f"{'TASK_ID':<18} {'TYPE':<16} {'DIFF':>4} {'REWARD':>7} {'TIME_LEFT':>10}")
    print("-" * 60)
    for t in tasks:
        print(
            f"{t['task_id']:<18} {t['task_type']:<16} {t['difficulty']:>4}"
            f" {t['credit_reward']:>7} {t['time_left_s']:>9}s"
        )
    return 0


def cmd_leaderboard(args) -> int:
    """Show the top contributing devices."""
    params = {"limit": args.limit}
    response = httpx.get(f"{args.api}/api/devices", params=params, timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    data = response.json()
    devices = data.get("devices", [])
    total = data.get("total_enrolled", len(devices))
    if not devices:
        print("No devices enrolled yet.")
        return 0
    print(f"Total enrolled: {total}")
    print(f"\n{'#':<4} {'DEVICE_ID':<24} {'CREDITS':>8} {'TASKS':>6} {'LAST_ACTIVE'}")
    print("-" * 60)
    for i, d in enumerate(devices, 1):
        last = d.get("last_active")
        if last:
            ts = datetime.datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M")
        else:
            ts = "—"
        print(
            f"{i:<4} {d['device_id']:<24} {d.get('credits_balance', 0):>8}"
            f" {d.get('tasks_contributed', 0):>6}  {ts}"
        )
    return 0


def cmd_status(args) -> int:
    """Show node status, task pool stats, and supply information."""
    response = httpx.get(f"{args.api}/api/status", timeout=10)
    if response.status_code >= 400:
        return _handle_error(response)
    _print_json(response.json())
    return 0


def cmd_join(args) -> int:
    """
    Join the compute pool.

    Enrolls the device, then continuously polls for open tasks, executes them
    locally, and submits results.  Credits are credited automatically when
    3-of-5 consensus is reached on the server.

    Press Ctrl-C to stop.
    """
    identity = _load_or_create_identity(
        args.device_id, args.identity_passphrase, args.identity_mnemonic
    )
    device_id = identity["device_id"]
    puf_entropy = identity["puf_entropy"]

    print(f"[join] Device: {device_id}")
    print(f"[join] Enrolling with node {args.api} …")
    if not _ensure_enrolled(args.api, device_id, puf_entropy):
        print("[join] ERROR: enroll failed — is the server running?")
        return 1
    print("[join] Enrolled. Polling for tasks …\n")

    tasks_done = 0
    total_credits = 0

    try:
        while True:
            # Fetch open tasks
            resp = httpx.get(f"{args.api}/api/tasks", timeout=10)
            if resp.status_code != 200:
                print(
                    f"[join] WARN: /api/tasks returned {resp.status_code}, retrying in {args.interval}s"
                )
                time.sleep(args.interval)
                continue

            tasks = resp.json().get("tasks", [])
            if not tasks:
                print(f"[join] No open tasks. Waiting {args.interval}s …")
                time.sleep(args.interval)
                continue

            # Pick first available task
            task_info = tasks[0]
            task_id = task_info["task_id"]
            print(
                f"[join] Executing task {task_id} (type={task_info['task_type']}, diff={task_info['difficulty']}) …"
            )

            # Fetch full spec
            detail_resp = httpx.get(f"{args.api}/api/task/{task_id}", timeout=10)
            if detail_resp.status_code != 200:
                print("[join] WARN: could not fetch task spec, skipping")
                time.sleep(2)
                continue

            detail = detail_resp.json()
            try:
                spec = TaskSpec.from_dict(
                    {
                        "task_id": task_id,
                        "task_type": detail["task_type"],
                        "difficulty": detail["difficulty"],
                        "input_data_hex": detail.get("input_data_hex", ""),
                        "expected_output_hash": detail.get("expected_output_hash", ""),
                        "credit_reward": detail.get("credit_reward", 10),
                    }
                )
                t0 = time.monotonic()
                result = execute_task(spec, timeout_s=args.timeout)
                elapsed = time.monotonic() - t0
                print(
                    f"[join]   ✓ executed in {elapsed:.2f}s — output_hash={result.output_hash[:16]}…"
                )
            except Exception as exc:
                print(f"[join]   ✗ execution failed: {exc}")
                time.sleep(2)
                continue

            # Submit result
            sig = _make_sig(puf_entropy, f"{device_id}:{task_id}")
            submit_resp = httpx.post(
                f"{args.api}/api/task/{task_id}/result",
                json={
                    "device_id": device_id,
                    "output_hash": result.output_hash,
                    "exec_time_s": result.execution_time_s,
                    "has_tee": False,
                },
                headers={"X-Device-Sig": sig},
                timeout=15,
            )
            if submit_resp.status_code == 200:
                v = submit_resp.json()
                status = v.get("status", "?")  # noqa: F841
                credits_earned = v.get("credits_earned", 0)
                total_credits += credits_earned
                tasks_done += 1
                if v.get("verified"):
                    print(
                        f"[join]   💰 CONSENSUS REACHED — earned {credits_earned} credits (total: {total_credits})"
                    )
                else:
                    needed = v.get("consensus_needed", "?")
                    print(
                        f"[join]   ⏳ pending consensus ({needed} more proofs needed)"
                    )
            else:
                print(
                    f"[join]   WARN: submit returned {submit_resp.status_code}: {submit_resp.text[:80]}"
                )

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(
            f"\n[join] Stopped. Tasks executed: {tasks_done}, Total credits earned: {total_credits}"
        )
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tfp", description="TFP demo CLI")
    parser.add_argument("--api", default=DEFAULT_API, help="TFP demo API base URL")
    parser.add_argument(
        "--identity-passphrase",
        default=os.environ.get("TFP_IDENTITY_PASSPHRASE", ""),
        help="Passphrase for encrypted identity storage (v3.2 identity module)",
    )
    parser.add_argument(
        "--identity-mnemonic",
        default=os.environ.get("TFP_IDENTITY_MNEMONIC", ""),
        help="Optional recovery mnemonic when creating encrypted identities",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish", help="Publish text content")
    publish.add_argument("--title", required=True, help="Content title")
    publish.add_argument("--text", required=True, help="Content body text")
    publish.add_argument("--tags", default="", help="Comma-separated tags")
    publish.add_argument(
        "--device-id", default="cli-user", dest="device_id", help="Device id"
    )
    publish.set_defaults(func=cmd_publish)

    get = sub.add_parser("get", help="Fetch content by root hash")
    get.add_argument("root_hash", help="Content root hash")
    get.add_argument(
        "--device-id",
        default="cli-user",
        dest="device_id",
        help="Device id for credit accounting",
    )
    get.set_defaults(func=cmd_get)

    earn = sub.add_parser("earn", help="Earn credits by submitting compute task")
    earn.add_argument(
        "--task-id", required=True, dest="task_id", help="Task recipe identifier"
    )
    earn.add_argument(
        "--device-id",
        default="cli-user",
        dest="device_id",
        help="Device id for credit accounting",
    )
    earn.set_defaults(func=cmd_earn)

    search = sub.add_parser("search", help="List or search published content")
    search.add_argument("--tag", help="Filter by a single tag")
    search.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags — returns items matching any (union)",
    )
    search.add_argument(
        "--limit", type=int, default=20, help="Max results per page (default: 20)"
    )
    search.add_argument(
        "--offset", type=int, default=0, help="Pagination offset (default: 0)"
    )
    search.set_defaults(func=cmd_search)

    status_cmd = sub.add_parser("status", help="Show node status and task pool")
    status_cmd.set_defaults(func=cmd_status)

    tasks_cmd = sub.add_parser("tasks", help="List open compute tasks")
    tasks_cmd.add_argument(
        "--limit", type=int, default=20, help="Max tasks to show (default: 20)"
    )
    tasks_cmd.set_defaults(func=cmd_tasks)

    leaderboard_cmd = sub.add_parser(
        "leaderboard", help="Show top contributing devices"
    )
    leaderboard_cmd.add_argument(
        "--limit", type=int, default=20, help="Max devices to show (default: 20)"
    )
    leaderboard_cmd.set_defaults(func=cmd_leaderboard)

    join = sub.add_parser(
        "join", help="Join the compute pool — execute tasks and earn credits"
    )
    join.add_argument(
        "--device-id",
        default=f"cli-{os.getpid()}",
        dest="device_id",
        help="Device id (auto-generated per-process if not set)",
    )
    join.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Polling interval between tasks in seconds (default: 2)",
    )
    join.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Max seconds per task execution (default: 30)",
    )
    join.set_defaults(func=cmd_join)

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
