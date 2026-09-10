# Verification & Trust Guide

This document explains the rigorous verification process used by the AI to ensure every code change in The Foundation Protocol is correct, secure, and trustable.

## 1. The "Verified-First" Workflow
Every change follows a strict lifecycle:
1.  **Deep-Scan**: The AI searches the codebase to understand all dependencies and structures.
2.  **Explicit Spec**: A detailed plan is created in `.trae/specs/` before any code is written.
3.  **Zero-Assumption Coding**: Implementation is based only on verified facts, never guesses.
4.  **Evidence-Based Proof**: Every task is verified using automated tests or verifiable logs.

## 2. How to Read Verification Proofs
When the AI completes a task, it provides a "Verification Proof." This usually includes:
- **Test Results**: Output from tools like `pytest` showing specific scenarios that were tested.
- **Log Snippets**: Server logs demonstrating the new behavior in action.
- **Visual Proof**: In web-based changes, a link to the preview.

## 3. How You Can Verify the Work
Even if you have limited programming knowledge, you can run simple commands to confirm the work is correct.

### Example: Verifying the Upload Size Limit (SEC-001)
To verify that the server now correctly rejects oversized uploads:
1.  Ensure the server is running.
2.  Run the automated test script:
    ```bash
    pytest tfp-foundation-protocol/tests/test_sec_001.py
    ```
3.  If the output says `3 passed`, the fix is working as intended.

## 4. Reporting Trust Issues
If you ever feel a change is not sufficiently verified, you can ask for a "Deep Proof." The AI will then:
1.  Explain the internal logic of the change in plain English.
2.  Create an additional edge-case test to prove resilience.
3.  Trace the change's impact across all affected files.
