#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Advanced TFP Demo - Multi-Scenario Experience

This script provides several advanced demo scenarios:
1. Compute Pool Participation - Join and earn credits
2. Content Publishing with Tags - Rich content publishing
3. Multi-Device Simulation - Simulate multiple devices
4. Nostr Integration - Content gossip via Nostr
5. Performance Testing - Measure system performance
"""

import subprocess
import sys
import time
import json
import urllib.request
import urllib.error
import io
import hmac
import hashlib
import os

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def log(msg, level="INFO"):
    """Log with timestamp and visual indicators"""
    timestamp = time.strftime('%H:%M:%S')
    symbols = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "ERROR": "❌",
        "WARN": "⚠️",
        "PROGRESS": "🔄",
        "SCENARIO": "🎯"
    }
    symbol = symbols.get(level, "ℹ️")
    print(f"[{timestamp}] {symbol} {msg}")

def wait_for_server(url, timeout=30):
    """Wait for server to become ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.URLError:
            time.sleep(0.5)
    return False

def api_call(method, path, data=None, headers=None):
    """Make API call to demo server."""
    url = f"http://localhost:8000{path}"
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}

def generate_device_sig(device_id, puf_entropy, message):
    """Generate HMAC-SHA-256 signature for device authentication."""
    entropy_bytes = bytes.fromhex(puf_entropy)
    sig = hmac.new(entropy_bytes, message.encode(), hashlib.sha256).hexdigest()
    return sig

def scenario_compute_pool():
    """Scenario 1: Compute Pool Participation"""
    log("=" * 60, "SCENARIO")
    log("Scenario 1: Compute Pool Participation", "SCENARIO")
    log("=" * 60, "SCENARIO")
    
    device_id = "compute-worker-001"
    puf_entropy = os.urandom(32).hex()
    
    # Enroll device
    log("Enrolling compute worker device...", "PROGRESS")
    result = api_call("POST", "/api/enroll", {
        "device_id": device_id, 
        "puf_entropy_hex": puf_entropy
    })
    if "error" in result:
        log(f"Enroll failed: {result['error']}", "ERROR")
        return False
    log(f"Device enrolled: {device_id}", "SUCCESS")
    
    # Earn credits from multiple tasks
    log("Processing compute tasks to earn credits...", "PROGRESS")
    total_earned = 0
    for i in range(5):
        task_id = f"compute-task-{i}"
        message = f"{device_id}:{task_id}"
        sig = generate_device_sig(device_id, puf_entropy, message)
        
        result = api_call("POST", "/api/earn", {
            "device_id": device_id, 
            "task_id": task_id
        }, headers={"X-Device-Sig": sig})
        
        if "error" not in result:
            earned = result.get('credits_earned', 0)
            total_earned += earned
            log(f"Task {i+1}/5: Earned {earned} credits", "SUCCESS")
        else:
            log(f"Task {i+1}/5: Failed - {result.get('error', 'Unknown')}", "WARN")
        
        time.sleep(0.5)  # Small delay between tasks
    
    log(f"Total credits earned: {total_earned}", "SUCCESS")
    return True

def scenario_content_publishing():
    """Scenario 2: Rich Content Publishing with Tags"""
    log("=" * 60, "SCENARIO")
    log("Scenario 2: Rich Content Publishing with Tags", "SCENARIO")
    log("=" * 60, "SCENARIO")
    
    device_id = "content-publisher-001"
    puf_entropy = os.urandom(32).hex()
    
    # Enroll device
    log("Enrolling content publisher device...", "PROGRESS")
    result = api_call("POST", "/api/enroll", {
        "device_id": device_id, 
        "puf_entropy_hex": puf_entropy
    })
    if "error" in result:
        log(f"Enroll failed: {result['error']}", "ERROR")
        return False
    log(f"Device enrolled: {device_id}", "SUCCESS")
    
    # Publish multiple content items with different tags
    content_items = [
        {
            "title": "Introduction to TFP",
            "text": "The Foundation Protocol is a decentralized content and compute protocol designed for global information access.",
            "tags": ["education", "introduction", "tfp"]
        },
        {
            "title": "Compute Pool Mechanics",
            "text": "Devices can join the compute pool to earn credits by executing verifiable tasks. Credits are minted via HABP consensus.",
            "tags": ["technical", "compute", "consensus"]
        },
        {
            "title": "Security Features",
            "text": "TFP uses PUF/TEE identity, HMAC device authentication, and post-quantum cryptographic agility for maximum security.",
            "tags": ["security", "cryptography", "privacy"]
        }
    ]
    
    published_hashes = []
    for i, content in enumerate(content_items):
        log(f"Publishing content {i+1}/{len(content_items)}: {content['title']}", "PROGRESS")
        
        message = f"{device_id}:{content['title']}"
        sig = generate_device_sig(device_id, puf_entropy, message)
        
        start = time.time()
        result = api_call("POST", "/api/publish", {
            "device_id": device_id,
            **content
        }, headers={"X-Device-Sig": sig})
        publish_time = (time.time() - start) * 1000
        
        if "error" not in result:
            content_hash = result.get("root_hash", "unknown")
            published_hashes.append(content_hash)
            log(f"Published in {publish_time:.0f}ms - Hash: {content_hash[:16]}...", "SUCCESS")
        else:
            log(f"Publish failed: {result['error']}", "ERROR")
    
    # Retrieve and verify content
    log("Retrieving published content for verification...", "PROGRESS")
    for i, content_hash in enumerate(published_hashes):
        result = api_call("GET", f"/api/get/{content_hash}?device_id={device_id}")
        if "error" not in result:
            original = content_items[i]
            retrieved = result
            if retrieved.get('title') == original['title'] and retrieved.get('text') == original['text']:
                log(f"Content {i+1} verified successfully", "SUCCESS")
            else:
                log(f"Content {i+1} verification failed", "ERROR")
        else:
            log(f"Retrieval failed for content {i+1}", "ERROR")
    
    return True

def scenario_multi_device():
    """Scenario 3: Multi-Device Simulation"""
    log("=" * 60, "SCENARIO")
    log("Scenario 3: Multi-Device Simulation", "SCENARIO")
    log("=" * 60, "SCENARIO")
    
    num_devices = 3
    devices = []
    
    # Create multiple devices
    for i in range(num_devices):
        device_id = f"simulated-device-{i:03d}"
        puf_entropy = os.urandom(32).hex()
        devices.append({"device_id": device_id, "puf_entropy": puf_entropy})
        
        log(f"Enrolling device {i+1}/{num_devices}: {device_id}", "PROGRESS")
        result = api_call("POST", "/api/enroll", {
            "device_id": device_id, 
            "puf_entropy_hex": puf_entropy
        })
        if "error" not in result:
            log(f"Device {device_id} enrolled", "SUCCESS")
        else:
            log(f"Device enrollment failed: {result['error']}", "ERROR")
    
    # Each device publishes content
    log("Each device publishing content...", "PROGRESS")
    for i, device in enumerate(devices):
        message = f"{device['device_id']}:Multi-device test"
        sig = generate_device_sig(device['device_id'], device['puf_entropy'], message)
        
        result = api_call("POST", "/api/publish", {
            "device_id": device['device_id'],
            "title": f"Content from {device['device_id']}",
            "text": f"This is content published by device {i+1} in the multi-device simulation.",
            "tags": ["multi-device", f"device-{i}"]
        }, headers={"X-Device-Sig": sig})
        
        if "error" not in result:
            log(f"Device {device['device_id']} published content", "SUCCESS")
        else:
            log(f"Publish failed for {device['device_id']}", "ERROR")
    
    # Check overall content list
    log("Checking overall content availability...", "PROGRESS")
    result = api_call("GET", "/api/content")
    if "error" not in result:
        content_count = len(result.get('content', []))
        log(f"Total content items in network: {content_count}", "SUCCESS")
    else:
        log("Failed to retrieve content list", "ERROR")
    
    return True

def scenario_performance_test():
    """Scenario 4: Performance Testing"""
    log("=" * 60, "SCENARIO")
    log("Scenario 4: Performance Testing", "SCENARIO")
    log("=" * 60, "SCENARIO")
    
    device_id = "perf-test-device"
    puf_entropy = os.urandom(32).hex()
    
    # Enroll device
    log("Enrolling performance test device...", "PROGRESS")
    result = api_call("POST", "/api/enroll", {
        "device_id": device_id, 
        "puf_entropy_hex": puf_entropy
    })
    if "error" in result:
        log(f"Enroll failed: {result['error']}", "ERROR")
        return False
    log(f"Device enrolled: {device_id}", "SUCCESS")
    
    # Performance test: Publish latency
    log("Testing publish latency (10 iterations)...", "PROGRESS")
    publish_times = []
    for i in range(10):
        message = f"{device_id}:Perf test {i}"
        sig = generate_device_sig(device_id, puf_entropy, message)
        
        start = time.time()
        result = api_call("POST", "/api/publish", {
            "device_id": device_id,
            "title": f"Performance Test {i}",
            "text": "Performance testing content",
            "tags": ["performance", "test"]
        }, headers={"X-Device-Sig": sig})
        publish_time = (time.time() - start) * 1000
        
        if "error" not in result:
            publish_times.append(publish_time)
            log(f"Iteration {i+1}/10: {publish_time:.0f}ms", "INFO")
    
    if publish_times:
        avg_time = sum(publish_times) / len(publish_times)
        min_time = min(publish_times)
        max_time = max(publish_times)
        log(f"Publish latency - Avg: {avg_time:.0f}ms, Min: {min_time:.0f}ms, Max: {max_time:.0f}ms", "SUCCESS")
    
    # Performance test: Retrieve latency
    if publish_times:
        log("Testing retrieve latency (10 iterations)...", "PROGRESS")
        # First publish a content item to retrieve
        message = f"{device_id}:Retrieve test"
        sig = generate_device_sig(device_id, puf_entropy, message)
        result = api_call("POST", "/api/publish", {
            "device_id": device_id,
            "title": "Retrieve Test Content",
            "text": "Content for retrieve performance testing",
            "tags": ["performance", "retrieve"]
        }, headers={"X-Device-Sig": sig})
        
        if "error" not in result:
            content_hash = result.get("root_hash")
            retrieve_times = []
            
            for i in range(10):
                start = time.time()
                result = api_call("GET", f"/api/get/{content_hash}?device_id={device_id}")
                retrieve_time = (time.time() - start) * 1000
                
                if "error" not in result:
                    retrieve_times.append(retrieve_time)
                    log(f"Iteration {i+1}/10: {retrieve_time:.0f}ms", "INFO")
            
            if retrieve_times:
                avg_time = sum(retrieve_times) / len(retrieve_times)
                min_time = min(retrieve_times)
                max_time = max(retrieve_times)
                log(f"Retrieve latency - Avg: {avg_time:.0f}ms, Min: {min_time:.0f}ms, Max: {max_time:.0f}ms", "SUCCESS")
    
    return True

def main():
    log("=" * 60, "INFO")
    log("TFP Advanced Demo - Multi-Scenario Experience", "INFO")
    log("=" * 60, "INFO")
    
    # Start server in background
    log("Starting TFP demo server...", "PROGRESS")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tfp_demo.server:app", 
         "--host", "127.0.0.1", "--port", "8000"],
        cwd="tfp-foundation-protocol",
        env={**dict(subprocess.os.environ), "TFP_DB_PATH": ":memory:", "PYTHONPATH": "."},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    if not wait_for_server("http://localhost:8000/health"):
        log("ERROR: Server failed to start", "ERROR")
        server_proc.terminate()
        return 1
    log("Server ready on http://localhost:8000", "SUCCESS")
    
    try:
        # Run scenarios
        scenarios = [
            ("Compute Pool Participation", scenario_compute_pool),
            ("Rich Content Publishing", scenario_content_publishing),
            ("Multi-Device Simulation", scenario_multi_device),
            ("Performance Testing", scenario_performance_test)
        ]
        
        print("\nAvailable scenarios:")
        for i, (name, _) in enumerate(scenarios, 1):
            print(f"  {i}. {name}")
        print("  5. Run all scenarios")
        print("  0. Exit")
        
        choice = input("\nSelect scenario (0-5): ").strip()
        
        if choice == "0":
            log("Exiting demo", "INFO")
        elif choice == "5":
            log("Running all scenarios...", "PROGRESS")
            for name, scenario_func in scenarios:
                log(f"\n{'='*60}", "INFO")
                log(f"Starting: {name}", "SCENARIO")
                scenario_func()
                time.sleep(1)
        elif choice.isdigit() and 1 <= int(choice) <= len(scenarios):
            scenario_name, scenario_func = scenarios[int(choice) - 1]
            log(f"\nRunning: {scenario_name}", "SCENARIO")
            scenario_func()
        else:
            log("Invalid choice, running first scenario", "WARN")
            scenarios[0][1]()
        
        log("\n" + "=" * 60, "INFO")
        log("Advanced Demo Complete!", "SUCCESS")
        log("=" * 60, "INFO")
        log("Check the admin dashboard: http://localhost:8000/admin", "INFO")
        log("Press Enter to shut down server...", "INFO")
        input()
        
    finally:
        log("Shutting down server...", "INFO")
        server_proc.terminate()
        server_proc.wait()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())