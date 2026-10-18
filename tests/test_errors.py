"""Unit tests for error_report.extract_failure."""

import unittest

from error_report import describe_incomplete, extract_failure

# Purely synthetic, non-functional placeholder credential.
DUMMY_SECRET = "sk-dummy-test-token-0000"


def redact_dummy(value):
    return value.replace(DUMMY_SECRET, "[REDACTED]")


def error_event(code, message):
    return {
        "type": "turn/end",
        "data": {
            "reason": {
                "kind": "error",
                "error": {"code": code, "message": message},
            }
        },
    }


class ExtractFailureTests(unittest.TestCase):
    def test_terminal_transport_extraction(self):
        events = [
            {"type": "turn/start", "data": {}},
            error_event("TRANSPORT", "connection dropped"),
        ]

        result = extract_failure(events, redact_dummy)

        self.assertEqual(
            result,
            {"code": "TRANSPORT", "message": "connection dropped"},
        )

    def test_last_terminal_failure_wins(self):
        events = [
            error_event("OLD", "older failure"),
            error_event("NEW", "newer failure"),
        ]

        result = extract_failure(events, redact_dummy)

        self.assertEqual(result["code"], "NEW")
        self.assertEqual(result["message"], "newer failure")

    def test_redact_applied_and_output_bounded(self):
        long_code = "C" * 200
        long_message = ("prefix " + DUMMY_SECRET + " ") + ("x" * 5000)

        result = extract_failure(
            [error_event(long_code, long_message)], redact_dummy
        )

        self.assertNotIn(DUMMY_SECRET, result["message"])
        self.assertIn("[REDACTED]", result["message"])
        self.assertLessEqual(len(result["code"]), 80)
        self.assertLessEqual(len(result["message"]), 2000)

    def test_malformed_event_shapes_return_none_without_throwing(self):
        malformed_cases = [
            None,
            42,
            [],
            [None],
            ["not-a-dict"],
            [{}],
            [{"type": "turn/end"}],
            [{"type": "turn/end", "data": None}],
            [{"type": "turn/end", "data": {}}],
            [{"type": "turn/end", "data": {"reason": "oops"}}],
            [
                {
                    "type": "turn/end",
                    "data": {"reason": {"kind": "aborted"}},
                }
            ],
            [{"type": "other", "data": {"reason": {"kind": "error"}}}],
        ]

        for events in malformed_cases:
            with self.subTest(events=events):
                self.assertIsNone(extract_failure(events, redact_dummy))


class DescribeIncompleteTests(unittest.TestCase):
    def test_max_tokens_reports_configured_limit(self):
        result = describe_incomplete("max-tokens", max_output_tokens=65536)

        self.assertEqual(result["code"], "OUTPUT_TOKEN_LIMIT")
        self.assertIn("65536", result["message"])
        self.assertLessEqual(len(result["message"]), 2000)

    def test_max_tokens_is_not_quota_or_balance_exhaustion(self):
        result = describe_incomplete("max-tokens", max_output_tokens=65536)

        self.assertEqual(result["code"], "OUTPUT_TOKEN_LIMIT")
        self.assertNotIn(
            result["code"],
            {"QUOTA_EXCEEDED", "BALANCE_EXHAUSTED", "INSUFFICIENT_BALANCE"},
        )
        self.assertIn("not an account-balance", result["message"])

    def test_max_tokens_malformed_max_values_do_not_crash(self):
        for value in (None, True, False, 0, -1, "65536", 3.5, object()):
            with self.subTest(max_output_tokens=value):
                result = describe_incomplete(
                    "max-tokens", max_output_tokens=value
                )
                self.assertEqual(result["code"], "OUTPUT_TOKEN_LIMIT")
                self.assertLessEqual(len(result["message"]), 2000)
                self.assertNotIn("65536", result["message"])

    def test_other_reasons_are_incomplete_and_bounded(self):
        self.assertEqual(
            describe_incomplete(None),
            {"code": "INCOMPLETE", "message": "Harness stopped: unknown"},
        )
        result = describe_incomplete("aborted")
        self.assertEqual(result["code"], "INCOMPLETE")
        self.assertEqual(result["message"], "Harness stopped: aborted")

        for reason in ("x" * 5000, 42, {"unexpected": "shape"}):
            with self.subTest(reason=reason):
                result = describe_incomplete(reason)
                self.assertEqual(result["code"], "INCOMPLETE")
                self.assertTrue(result["message"].startswith("Harness stopped: "))
                self.assertLessEqual(len(result["message"]), 2000)


if __name__ == "__main__":
    unittest.main()
