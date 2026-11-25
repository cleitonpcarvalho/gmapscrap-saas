"""Opt-in smoke test of the actual app; API and temp/instance state are isolated."""
import json
import os
from pathlib import Path
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest


def test_packaged_app_launches_loads_registry_and_prevents_second_instance(tmp_path):
    app_path = os.getenv("GMAPSCRAP_TEST_APP_PATH")
    if not app_path:
        pytest.skip("Set GMAPSCRAP_TEST_APP_PATH to a built local GmapScrap.app")
    executable = Path(app_path) / "Contents/MacOS/GmapScrap"
    assert executable.is_file()
    history, niches = Event(), Event()
    calls = []
    class Api(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            calls.append(("POST", self.path))
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.respond(200 if self.path == "/api/auth/login" else 405, {"username": "local-smoke"})
        def do_GET(self):
            calls.append(("GET", self.path))
            if self.path == "/api/searches":
                self.respond(200, [])
                history.set()
            elif self.path.startswith("/api/niches"):
                self.respond(200, [{"id": 1, "name": "Local QA"}])
                niches.set()
            else:
                self.respond(405, {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Api)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    isolated_temp = tmp_path / "runtime"
    isolated_temp.mkdir()
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", TMPDIR=str(isolated_temp),
               GMAPSCRAP_STATE_DIR=str(tmp_path / "state"),
               GMAPSCRAP_API_BASE_URL=f"http://127.0.0.1:{server.server_port}",
               GMAPSCRAP_API_USERNAME="local-smoke", GMAPSCRAP_API_PASSWORD="local-test-only")
    processes = []
    try:
        with (tmp_path / "package.log").open("w+") as log:
            first = subprocess.Popen([str(executable)], env=env, stdout=log, stderr=log)
            processes.append(first)
            assert history.wait(15), "Package did not load history from the local API"
            assert niches.wait(15), "Package did not load the local registry"
            assert first.poll() is None
            second = subprocess.Popen([str(executable)], env=env, stdout=log, stderr=log)
            processes.append(second)
            assert second.wait(timeout=10) == 0
            assert first.poll() is None
            assert all(path == "/api/auth/login" for method, path in calls if method == "POST")
            assert all(method in {"GET", "POST"} for method, _ in calls)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
