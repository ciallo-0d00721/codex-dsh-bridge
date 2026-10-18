"""Real pinned DSH runtime + local fake Messages provider; no paid request."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

import bridge


class RuntimeIntegrationTests(unittest.TestCase):
    def exercise(self, mode):
        task_root = bridge.workspace_path("offline-test", bridge.config()).parent
        task_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=task_root, prefix="offline-integration-") as folder:
            base = Path(folder).resolve()
            self.assertTrue(base.is_relative_to(task_root.resolve()))
            workspace = base / "workspace"
            bridge.prepare_workspace(workspace)
            outside = base / "outside-should-not-exist.txt"
            requests = []

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    requests.append({"path": self.path, "body": body})
                    if mode in {"error", "quota"}:
                        data = json.dumps({"type": "error", "error": {
                            "type": "insufficient_quota_error" if mode == "quota" else "invalid_request_error",
                            "message": "Offline synthetic quota exhausted" if mode == "quota" else "Offline synthetic request failure"}}).encode()
                        self.send_response(402 if mode == "quota" else 400)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    tools = [{"name": t["name"], "parameters": t["input_schema"]} for t in body.get("tools", [])]
                    tool_use = (mode not in {"text", "resume", "max-tokens"} and len(requests) == 1) or (mode == "escalate" and len(requests) == 2)
                    if tool_use:
                        tool_name = "pwsh" if mode.startswith("shell") else "write"
                        tool = next(t for t in tools if t.get("name") == tool_name)
                        props = tool["parameters"]["properties"]
                        target = outside if "deny" in mode or mode == "escalate" else workspace / "verified.txt"
                        if mode.startswith("shell"):
                            args = {"command": "Set-Content -LiteralPath '" + str(target).replace("'", "''") +
                                    "' -Value 'OFFLINE_RUNTIME_WRITE_OK'", "description": "Write a disposable offline test fixture",
                                    "timeoutMs": 15000}
                        else:
                            path_key = next(k for k in ("file_path", "path", "filePath") if k in props)
                            content_key = next(k for k in ("content", "text") if k in props)
                            args = {path_key: str(target), content_key: "OFFLINE_RUNTIME_WRITE_OK\n"}
                            if mode == "escalate" and len(requests) == 2:
                                args.update(sandbox_permissions="danger-full-access", justification="Offline negative test of rejected escalation")
                        block = {"type": "tool_use", "id": "tool_offline_1", "name": tool_name, "input": {}}
                        delta = {"type": "input_json_delta", "partial_json": json.dumps(args)}
                        reason = "tool_use"
                    else:
                        block = {"type": "text", "text": ""}
                        delta = {"type": "text_delta", "text": "OFFLINE_RUNTIME_RESPONSE_OK"}
                        reason = "max_tokens" if mode == "max-tokens" else "end_turn"
                    events = [
                        ("message_start", {"type": "message_start", "message": {"id": "msg_offline", "type": "message",
                         "role": "assistant", "model": "deepseek-flash", "content": [], "stop_reason": None,
                         "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 0}}}),
                        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": block}),
                        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
                        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": reason, "stop_sequence": None},
                         "usage": {"output_tokens": 5}}),
                        ("message_stop", {"type": "message_stop"}),
                    ]
                    data = "".join(f"event: {name}\ndata: {json.dumps(value)}\n\n" for name, value in events).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            notifications = []
            try:
                settings = bridge.config()
                options = bridge.harness_options(workspace, base / "home", settings, "offline-test-not-a-real-key")
                options["base_url"] = f"http://127.0.0.1:{server.server_port}"
                options["request_timeout_seconds"] = 15
                with bridge.managed_harness(options) as harness:
                    result = harness.run("Execute the local offline integration fixture.",
                                         session_id="offline-test-session", on_notification=notifications.append)
                self.assertTrue(requests)
                for request in requests:
                    self.assertEqual(request["body"]["max_tokens"], settings["max_output_tokens_per_request"])
                    self.assertEqual(request["body"]["output_config"]["effort"], "high")
                if mode == "max-tokens":
                    self.assertEqual(result.finish_reason, "max-tokens")
                    output = bridge.worker_result(result, workspace, 1, "offline-test-not-a-real-key", settings)
                    self.assertEqual(output["error"]["code"], "OUTPUT_TOKEN_LIMIT")
                    self.assertIn("65536", output["error"]["message"])
                    self.assertFalse(output["model_completed"])
                    self.assertFalse(output["accepted_by_coordinator"])
                    self.assertEqual(len(requests), 1, "Output truncation must not automatically retry")
                    return
                if mode == "quota":
                    self.assertEqual(result.finish_reason, "error")
                    output = bridge.worker_result(result, workspace, 1, "offline-test-not-a-real-key", settings)
                    self.assertEqual(output["error"]["code"], "QUOTA")
                    self.assertFalse(output["model_completed"])
                    self.assertEqual(len(requests), 1, "Account quota errors must not automatically retry")
                    return
                if mode == "error":
                    self.assertEqual(result.finish_reason, "error")
                    output = bridge.worker_result(result, workspace, 1, "offline-test-not-a-real-key")
                    self.assertFalse(output["model_completed"])
                    self.assertIn("Offline synthetic request failure", output["error"]["message"])
                    self.assertTrue(output["error"]["code"])
                    progress = [bridge.progress_record(n) for n in notifications]
                    self.assertTrue(any(p.get("error") == output["error"] for p in progress))
                    self.assertEqual(len(requests), 1, "Non-retryable errors must not be retried")
                    return
                if mode == "resume":
                    with bridge.managed_harness(options) as harness:
                        result = harness.run("Previous worker report: OFFLINE_RUNTIME_RESPONSE_OK. Inspect the existing files and do the new rework task.",
                                             session_id="offline-rework-session", on_notification=notifications.append)
                    self.assertIn("OFFLINE_RUNTIME_RESPONSE_OK", json.dumps(requests[-1]["body"]["messages"]))
                self.assertEqual(result.finish_reason, "completed", str({"end": [e for e in result.events if e.get("type") == "turn/end"],
                                 "requests": [{"path": r["path"], "keys": list(r["body"]),
                                 "tool_names": [t["name"] for t in r["body"].get("tools", [])]} for r in requests]}))
                self.assertEqual(result.final_response, "OFFLINE_RUNTIME_RESPONSE_OK")
                self.assertTrue(notifications)
                counted = 0
                for notification in notifications:
                    counted = bridge.count_model_step(notification, counted, 12)
                self.assertEqual(counted, len(requests), "Model-step guard must see the actual runtime step events")
                self.assertEqual(len(requests), 1 if mode == "text" else 3 if mode == "escalate" else 2)
                self.assertTrue(all(r["path"] == "/v1/messages" for r in requests))
                for request in requests:
                    self.assertNotIn("dsh_session_log", request["body"])
                    self.assertNotIn("dsh_plugin_packages", request["body"])
                    names = {t["name"] for t in request["body"].get("tools", [])}
                    self.assertNotIn("subagent", names)
                    self.assertNotIn("subagent_fork", names)
                if mode in {"write", "shell-write"}:
                    self.assertTrue((workspace / "verified.txt").exists(), str(requests[-1]["body"].get("messages", [])[-1:]))
                    self.assertEqual((workspace / "verified.txt").read_text(), "OFFLINE_RUNTIME_WRITE_OK\n")
                if mode in {"deny", "shell-deny", "escalate"}:
                    self.assertFalse(outside.exists(), "Filesystem-tool workspace boundary failed")
                    tool_results = [b for m in requests[-1]["body"].get("messages", [])
                                    for b in m.get("content", []) if isinstance(b, dict) and b.get("type") == "tool_result"]
                    self.assertTrue(any("denied" in str(b).lower() or "sandbox" in str(b).lower() or
                                        "unauthorized" in str(b).lower() for b in tool_results),
                                    "Denied write was not reported to the model: " + str(tool_results))
                if mode == "escalate":
                    self.assertTrue(any(e.get("type") == "approval/decided" and
                                        e.get("data", {}).get("outcome") == "rejected" for e in result.events),
                                    "Escalation rejection was not audited: " + str([e for e in result.events if str(e.get("type", "")).startswith("approval/")]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_real_runtime_text_and_event_return(self):
        self.exercise("text")

    def test_real_runtime_preserves_terminal_provider_error(self):
        self.exercise("error")

    def test_real_runtime_output_cap_is_distinct_from_account_quota(self):
        self.exercise("max-tokens")

    def test_real_runtime_account_quota_remains_a_quota_error(self):
        self.exercise("quota")

    def test_real_runtime_writes_inside_workspace(self):
        self.exercise("write")

    def test_real_runtime_refuses_outside_filesystem_write(self):
        self.exercise("deny")

    def test_real_runtime_shell_writes_inside_workspace(self):
        self.exercise("shell-write")

    def test_real_runtime_shell_refuses_outside_write(self):
        self.exercise("shell-deny")

    def test_real_runtime_fresh_session_rework_after_restart(self):
        self.exercise("resume")

    def test_real_runtime_rejects_full_access_escalation(self):
        self.exercise("escalate")


if __name__ == "__main__":
    unittest.main()
