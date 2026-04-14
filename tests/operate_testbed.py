#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Operational test for a 10-node TFP testbed.
Verifies messaging, audio clips, and video clips operation.
"""

import asyncio
import hashlib
import hmac
import logging
import random
import time
import secrets
from typing import Optional

try:
    import httpx
except ImportError:
    print("Please install httpx: pip install httpx")
    exit(1)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("TFP-OperationalTest")

NODE_PORTS = list(range(9001, 9011))
BASE_URL = "http://localhost"

# Operational sizes for verification
CONTENT_TYPES = {
    "message": {"size": 1024, "tag": "text"},
    "audio_clip": {"size": 512 * 1024, "tag": "audio"},  # 0.5 MB
    "video_clip": {"size": 5 * 1024 * 1024, "tag": "video"},  # 5 MB
}


class TFPTester:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.entropy = secrets.token_bytes(32)
        self.entropy_hex = self.entropy.hex()
        # Higher timeout for larger uploads
        self.client = httpx.AsyncClient(timeout=120.0)

    async def enroll_all(self):
        log.info(
            f"Checking health and enrolling device {self.device_id} on ALL 10 nodes..."
        )
        for port in NODE_PORTS:
            url_health = f"{BASE_URL}:{port}/health"
            # Wait for node to be fully ready (startup_stage='ready' + ready=True).
            # Health endpoint now exposes both fields, so we can gate on true readiness
            # rather than just "process is alive".
            for attempt in range(10):
                try:
                    h = await self.client.get(url_health)
                    if h.status_code == 200:
                        body = h.json()
                        if body.get("ready", False):
                            break
                        log.info(
                            f"  - Node {port}: alive but not ready yet "
                            f"(stage={body.get('startup_stage', '?')}), attempt {attempt + 1}/10"
                        )
                except Exception:
                    pass
                await asyncio.sleep(1)

            url = f"{BASE_URL}:{port}/api/enroll"
            payload = {"device_id": self.device_id, "puf_entropy_hex": self.entropy_hex}
            try:
                resp = await self.client.post(url, json=payload)
                resp.raise_for_status()
                log.info(f"  - Node {port}: Enrolled")
            except Exception as e:
                log.error(f"  - Node {port}: Enrollment Failed: {e}")
                raise

    def sign(self, message: str) -> str:
        return hmac.new(self.entropy, message.encode(), hashlib.sha256).hexdigest()

    async def earn_credits(self, port: int):
        log.info(f"Earning credits for {self.device_id} on port {port}...")
        # Get tasks
        resp = await self.client.get(f"{BASE_URL}:{port}/api/tasks")
        resp.raise_for_status()
        tasks = resp.json().get("tasks", [])

        if not tasks:
            log.info("No open tasks on this node, creating one...")
            payload = {"task_type": "hash_preimage", "difficulty": 3}
            resp = await self.client.post(f"{BASE_URL}:{port}/api/task", json=payload)
            resp.raise_for_status()
            task_id = resp.json()["task_id"]
        else:
            task_id = tasks[0]["task_id"]

        # Submit task for credits
        payload = {"device_id": self.device_id, "task_id": task_id}
        headers = {"X-Device-Sig": self.sign(f"{self.device_id}:{task_id}")}
        resp = await self.client.post(
            f"{BASE_URL}:{port}/api/earn", json=payload, headers=headers
        )
        resp.raise_for_status()
        log.info(
            f"SUCCESS: Earned credits. Receipt: {resp.json().get('chain_hash', '??')[:10]}..."
        )

    async def publish(self, content_type: str, stream: bool = False) -> str:
        port = random.choice(NODE_PORTS)
        spec = CONTENT_TYPES[content_type]
        title = f"op_{content_type}_{int(time.time())}"

        log.info(
            f"Publishing {content_type} ({spec['size'] / 1024:.0f} KB) to node on port {port} (streaming={stream})..."
        )

        headers = {"X-Device-Sig": self.sign(f"{self.device_id}:{title}")}

        start = time.time()
        if stream:
            files = {
                "file": ("blob.bin", b"A" * spec["size"], "application/octet-stream")
            }
            data = {
                "device_id": self.device_id,
                "title": title,
                "tags": f"{spec['tag']},ops-test",
            }
            resp = await self.client.post(
                f"{BASE_URL}:{port}/api/publish",
                data=data,
                files=files,
                headers=headers,
            )
        else:
            payload = {
                "device_id": self.device_id,
                "title": title,
                "text": "A" * spec["size"],
                "tags": [spec["tag"], "ops-test"],
            }
            resp = await self.client.post(
                f"{BASE_URL}:{port}/api/publish", json=payload, headers=headers
            )

        resp.raise_for_status()
        duration = time.time() - start

        root_hash = resp.json()["root_hash"]
        log.info(
            f"SUCCESS: Published {content_type}. RootHash: {root_hash[:10]}... (Time: {duration:.2f}s)"
        )
        return root_hash

    async def fetch(self, root_hash: str, label: str, stream: bool = False):
        # Pick a different random node for retrieval
        port = random.choice(NODE_PORTS)
        log.info(f"Retrieving {label} from node on port {port} (streaming={stream})...")

        start = time.time()
        params = {"device_id": self.device_id}
        if stream:
            params["stream"] = "true"

        resp = await self.client.get(
            f"{BASE_URL}:{port}/api/get/{root_hash}", params=params
        )

        if resp.status_code == 402:
            log.warning("Received 402 Payment Required. Earning credits...")
            await self.earn_credits(port)
            resp = await self.client.get(
                f"{BASE_URL}:{port}/api/get/{root_hash}", params=params
            )

        resp.raise_for_status()
        duration = time.time() - start

        if stream:
            chunks = 0
            async for _ in resp.aiter_bytes():
                chunks += 1
            log.info(
                f"SUCCESS: Retrieved {label} as {chunks} stream chunks. (Time: {duration:.2f}s)"
            )
        else:
            log.info(f"SUCCESS: Retrieved {label}. (Time: {duration:.2f}s)")

    async def delegate_proof(self):
        port = random.choice(NODE_PORTS)
        log.info(f"Testing ZKP Delegation Layer on port {port}...")
        circuit = "access_to_hash"
        private_claim = b"demo_private_key_material_00"
        payload = {
            "device_id": self.device_id,
            "circuit": circuit,
            "private_claim_hex": private_claim.hex(),
        }
        headers = {"X-Device-Sig": self.sign(f"{self.device_id}:{circuit}")}
        start = time.time()
        resp = await self.client.post(
            f"{BASE_URL}:{port}/api/delegate-proof", json=payload, headers=headers
        )
        resp.raise_for_status()
        duration = time.time() - start
        proof_hex = resp.json()["proof_hex"]
        log.info(
            f"SUCCESS: Delegated proof generated. Proof: {proof_hex[:16]}... (Time: {duration:.2f}s)"
        )


async def main():
    device_id = f"op-bot-{random.randint(100, 999)}"
    tester = TFPTester(device_id)

    log.info("=== Starting TFP 10-Node Operational Test (Fidelity Pass) ===")

    try:
        # 1. Enroll globally (since demo server session state is node-local)
        await tester.enroll_all()

        # 2. Publish various workloads
        msg_hash = await tester.publish("message")
        audio_hash = await tester.publish("audio_clip", stream=True)
        video_hash = await tester.publish("video_clip")

        log.info("Intermission: Giving nodes a moment to announce via Relay/IPFS...")
        await asyncio.sleep(2)

        # 3. Retrieve content cross-node
        await tester.fetch(msg_hash, "Message")
        await tester.fetch(audio_hash, "Audio Clip (Streamed Upload)")
        await tester.fetch(video_hash, "Video Clip", stream=True)

        # 4. Test Optional ZKP Delegation Layer
        await tester.delegate_proof()

        log.info("=== OPERATIONAL TEST COMPLETE: ALL SYSTEMS NOMINAL ===")

    except httpx.HTTPStatusError as e:
        log.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        log.error(f"Test failed with error: {e}")
    finally:
        await tester.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
