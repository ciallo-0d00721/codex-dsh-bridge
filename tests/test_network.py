"""Offline proxy routing and environment checks; no real credential or model request."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import bridge


class NetworkSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=bridge.STATE, prefix="network-test-")
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.scope = patch.object(bridge, "STATE", self.state)
        self.scope.start()
        self.addCleanup(self.scope.stop)
        self.env = patch.dict(bridge.os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def configure(self, value):
        (self.state / "network.json").write_text(json.dumps(value), encoding="utf-8")

    def test_no_settings_keeps_direct_connection(self):
        self.assertEqual(bridge.network_environment(), {})

    def test_local_proxy_survives_worker_environment_scrubbing(self):
        self.configure({"HTTPS_PROXY": "http://127.0.0.1:12345", "NO_PROXY": "example.internal"})
        with patch.dict(bridge.os.environ, {"OPENAI_API_KEY": "unrelated-credential"}):
            env = bridge.clean_environment()
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:12345")
        self.assertEqual(env["NO_PROXY"], "example.internal")
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_explicit_environment_overrides_local_proxy(self):
        self.configure({"HTTPS_PROXY": "http://127.0.0.1:12345"})
        with patch.dict(bridge.os.environ, {"https_proxy": "http://127.0.0.1:23456"}):
            self.assertEqual(bridge.network_environment()["HTTPS_PROXY"], "http://127.0.0.1:23456")
        with patch.dict(bridge.os.environ, {"HTTPS_PROXY": ""}):
            self.assertNotIn("HTTPS_PROXY", bridge.network_environment())

    def test_unreviewed_or_invalid_settings_fail_without_printing_values(self):
        for value in ({"NODE_TLS_REJECT_UNAUTHORIZED": "0"}, [],
                      {"HTTPS_PROXY": "socks5://private-user:private-password@proxy:1080"},
                      {"HTTPS_PROXY": "http://proxy:invalid"}, {"HTTPS_PROXY": 42},
                      {"HTTPS_PROXY": "http://private proxy:8080"}, {"HTTPS_PROXY": "http://proxy:8080/pac"},
                      {"NO_PROXY": "example\ninvalid"}):
            with self.subTest(value=type(value).__name__):
                self.configure(value)
                with self.assertRaises(bridge.BridgeError) as raised:
                    bridge.network_environment()
                self.assertNotIn("private-password", str(raised.exception))

    def test_network_check_never_reads_credential(self):
        response = json.dumps({"type": "network-check", "reachable": True,
                               "http_status": 401, "credential_sent": False, "paid_model_tasks": 0})
        with patch.object(bridge, "get_token", side_effect=AssertionError("Credential accessed")), \
             patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, response, "")), \
             patch("sys.stdout", new_callable=StringIO) as output:
            self.assertEqual(bridge.network_check(), 0)
        self.assertFalse(json.loads(output.getvalue())["credential_sent"])

    def test_network_check_invalid_output_is_failure(self):
        with patch.object(bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 2, "", "private-diagnostic")), \
             patch("sys.stdout", new_callable=StringIO) as output:
            self.assertEqual(bridge.network_check(), 2)
        self.assertNotIn("private-diagnostic", output.getvalue())


class NetworkTransportTests(unittest.TestCase):
    def exercise(self, proxied):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                seen.append((self.path, dict(self.headers)))
                self.send_response(401)
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://bridge-probe.invalid/check" if proxied else f"http://127.0.0.1:{server.server_port}/check"
            script = "import {checkNetwork} from './network-check.mjs'; console.log(JSON.stringify(await checkNetwork(" + json.dumps(url) + ", 2000)));"
            with tempfile.TemporaryDirectory(dir=bridge.STATE, prefix="proxy-routing-") as folder:
                settings = Path(folder)
                # A proxy with NO_PROXY=* would hide a regression in loopback bypass.
                proxy = f"http://127.0.0.1:{server.server_port}" if proxied else "http://127.0.0.1:1"
                (settings / "network.json").write_text(json.dumps({"HTTP_PROXY": proxy, "HTTPS_PROXY": proxy}))
                inherited = {k: v for k, v in bridge.os.environ.items()
                             if k.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}}
                with patch.object(bridge, "STATE", settings), patch.dict(bridge.os.environ, inherited, clear=True):
                    env = bridge.clean_environment()
                launch = json.loads((bridge.STATE / "runtime-launch.json").read_text(encoding="utf-8-sig"))
                result = subprocess.run([launch["node_path"], "--input-type=module", "-e", script],
                                        cwd=bridge.BASE, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            status = json.loads(result.stdout)
            self.assertTrue(status["reachable"])
            self.assertEqual(status["http_status"], 401)
            self.assertEqual(status["proxy_used"], proxied)
            self.assertEqual(status["paid_model_tasks"], 0)
            self.assertFalse(status["credential_sent"])
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][0], url if proxied else "/check")
            headers = {k.lower() for k in seen[0][1]}
            self.assertFalse({"authorization", "x-api-key", "proxy-authorization"} & headers)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_clean_worker_environment_routes_through_explicit_proxy(self):
        self.exercise(True)

    def test_loopback_fixture_bypasses_unreachable_proxy(self):
        self.exercise(False)


if __name__ == "__main__":
    unittest.main()
