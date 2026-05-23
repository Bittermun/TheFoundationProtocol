# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Simple HTTP server to run the Scholo Radio Pilot App PWA Mockup
"""

import http.server
import socketserver
import webbrowser
import os

PORT = 8080
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class SafeHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)


def start_server():
    os.chdir(DIRECTORY)
    # Allow port reuse to prevent address-already-in-use errors
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), SafeHandler) as httpd:
        print(f"Scholo Radio local server running at: http://localhost:{PORT}/index.html")
        print("Press Ctrl+C to terminate.")
        webbrowser.open(f"http://localhost:{PORT}/index.html")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down Scholo Radio server...")


if __name__ == "__main__":
    start_server()
