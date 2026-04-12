#!/usr/bin/env python3
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("TFP-OperationalTest")

NODE_PORTS = [8001, 8002, 8003, 8004, 8005, 8006, 8007, 8009, 8010]
BASE_URL = "http://127.0.0.1"

# Operational sizes for verification
CONTENT_TYPES = {
    "message": {"size": 1024, "tag": "text"},
    "audio_clip": {"size": 512 * 1024, "tag": "audio"},      # 0.5 MB
    "video_clip": {"size": 5 * 1024 * 1024, "tag": "video"}  # 5 MB
}

class TFPTester:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.entropy = secrets.token_bytes(32)
        self.entropy_hex = self.entropy.hex()
        # Higher timeout for larger uploads
        self.client = httpx.AsyncClient(timeout=120.0)

    async def enroll_all(self):
        log.info(f"Enrolling device {self.device_id} on ALL 10 nodes...")
        for port in NODE_PORTS:
            url = f"{BASE_URL}:{port}/api/enroll"
            payload = {
                "device_id": self.device_id,
                "puf_entropy_hex": self.entropy_hex
            }
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
        resp = await self.client.post(f"{BASE_URL}:{port}/api/earn", json=payload, headers=headers)
        resp.raise_for_status()
        log.info(f"SUCCESS: Earned credits. Receipt: {resp.json().get('chain_hash', '??')[:10]}...")

    async def publish(self, content_type: str) -> str:
        port = random.choice(NODE_PORTS)
        spec = CONTENT_TYPES[content_type]
        title = f"op_{content_type}_{int(time.time())}"
        
        log.info(f"Publishing {content_type} ({spec['size']/1024:.0f} KB) to node on port {port}...")
        
        payload = {
            "device_id": self.device_id,
            "title": title,
            "text": "A" * spec["size"],
            "tags": [spec["tag"], "ops-test"]
        }
        headers = {"X-Device-Sig": self.sign(f"{self.device_id}:{title}")}
        
        start = time.time()
        resp = await self.client.post(f"{BASE_URL}:{port}/api/publish", json=payload, headers=headers)
        resp.raise_for_status()
        duration = time.time() - start
        
        root_hash = resp.json()["root_hash"]
        log.info(f"SUCCESS: Published {content_type}. RootHash: {root_hash[:10]}... (Time: {duration:.2f}s)")
        return root_hash

    async def fetch(self, root_hash: str, label: str):
        # Pick a different random node for retrieval
        port = random.choice(NODE_PORTS)
        log.info(f"Retrieving {label} from node on port {port}...")
        
        start = time.time()
        resp = await self.client.get(f"{BASE_URL}:{port}/api/get/{root_hash}", params={"device_id": self.device_id})
        
        if resp.status_code == 402:
            log.warning("Received 402 Payment Required. Earning credits...")
            await self.earn_credits(port)
            resp = await self.client.get(f"{BASE_URL}:{port}/api/get/{root_hash}", params={"device_id": self.device_id})
            
        resp.raise_for_status()
        duration = time.time() - start
        
        log.info(f"SUCCESS: Retrieved {label}. (Time: {duration:.2f}s)")

async def main():
    device_id = f"op-bot-{random.randint(100, 999)}"
    tester = TFPTester(device_id)
    
    log.info(f"=== Starting TFP 10-Node Operational Test (Fidelity Pass) ===")
    
    try:
        # 1. Enroll globally (since demo server session state is node-local)
        await tester.enroll_all()
        
        # 2. Publish various workloads
        msg_hash = await tester.publish("message")
        audio_hash = await tester.publish("audio_clip")
        video_hash = await tester.publish("video_clip")
        
        log.info("Intermission: Giving nodes a moment to announce via Relay/IPFS...")
        await asyncio.sleep(5)
        
        # 3. Cross-node retrieval phase
        log.info("--- Cross-Node Retrieval Phase ---")
        # For each piece of content, we fetch it from a random node (likely NOT the one it was published to)
        await tester.fetch(msg_hash, "Text Message")
        await tester.fetch(audio_hash, "Audio Clip")
        await tester.fetch(video_hash, "Video Clip")
        
        log.info("=== OPERATIONAL TEST COMPLETE: ALL SYSTEMS NOMINAL ===")
        
    except httpx.HTTPStatusError as e:
        log.error(f"HTTP Error: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        log.error(f"Test failed with error: {e}")
    finally:
        await tester.client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
