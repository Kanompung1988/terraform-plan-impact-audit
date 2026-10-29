import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit.py"
spec = importlib.util.spec_from_file_location("tf_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PlanAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.base = {"format_version": "1.0", "resource_changes": []}

    def test_safe_fixture_no_findings(self):
        got = audit.analyze(audit.read_plan(self.root / "examples/safe-plan.json"))
        self.assertEqual(got["findings"], [])
        self.assertEqual(got["counts"]["update"], 1)

    def test_review_fixture_rule_coverage(self):
        got = audit.analyze(audit.read_plan(self.root / "examples/review-plan.json"))
        self.assertEqual({f["rule"] for f in got["findings"]}, set(audit.RULES) - {"TP003"})

    def test_no_sensitive_fields_in_outputs(self):
        d = audit.read_plan(self.root / "examples/review-plan.json")
        self.assertNotIn("DUMMY-DO-NOT-PRINT", json.dumps(audit.analyze(d)))

    def test_address_instance_key_redacted(self):
        got = audit.analyze(audit.read_plan(self.root / "examples/review-plan.json"))
        self.assertNotIn("sensitive-key", json.dumps(got))
        self.assertIn("[*]", next(f["location"] for f in got["findings"] if f["rule"] == "TP002"))

    def test_missing_format_rejected(self):
        with self.assertRaisesRegex(ValueError, "format_version"):
            audit.analyze({"resource_changes": []})

    def test_wrong_version_rejected(self):
        with self.assertRaises(ValueError):
            audit.analyze({"format_version": "2.0", "resource_changes": []})

    def test_state_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "plan"):
            audit.analyze({"format_version": "1.1", "values": {}})

    def test_nonobject_rejected(self):
        with self.assertRaises(ValueError):
            audit.analyze([])

    def test_actions_are_validated(self):
        d = dict(self.base, resource_changes=[{"change": {"actions": ["mystery"]}}])
        with self.assertRaises(ValueError):
            audit.analyze(d)

    def test_unexpected_two_action_sequence_rejected(self):
        d = dict(self.base, resource_changes=[{"change": {"actions": ["update", "delete"]}}])
        with self.assertRaises(ValueError):
            audit.analyze(d)

    def test_noop_not_reported(self):
        d = dict(self.base, resource_changes=[{"address": "aws_vpc.x", "change": {"actions": ["no-op"]}}])
        self.assertEqual(audit.analyze(d)["counts"]["no-op"], 1)

    def test_create_before_destroy_medium(self):
        d = dict(self.base, resource_changes=[{"address": "a", "change": {"actions": ["create", "delete"]}}])
        self.assertEqual(audit.analyze(d)["findings"][0]["rule"], "TP003")

    def test_unknown_nested_output(self):
        d = dict(self.base, output_changes={"o": {"change": {"actions": ["create"], "after_unknown": {"x": [False, True]}}}})
        self.assertEqual(audit.analyze(d)["findings"][0]["rule"], "TP007")

    def test_checks_without_fail(self):
        self.assertEqual(audit.analyze(dict(self.base, checks=[{"status": "unknown"}]))["findings"], [])

    def test_drift_noop_is_ignored(self):
        d = dict(self.base, resource_drift=[{"address": "a", "change": {"actions": ["no-op"]}}])
        self.assertEqual(audit.analyze(d)["findings"], [])

    def test_cap_enforced(self):
        with patch.object(audit, "MAX_CHANGES", 0):
            with self.assertRaises(ValueError):
                audit.analyze(dict(self.base, resource_changes=[{"change": {"actions": ["delete"]}}]))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "input.json"
            src.write_text(json.dumps(self.base))
            link = Path(td) / "link.json"
            link.symlink_to(src)
            with self.assertRaisesRegex(ValueError, "symlink"):
                audit.read_plan(link)

    def test_invalid_json_cli_exit_one(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{bad", encoding="utf-8")
            self.assertEqual(audit.main([str(p)]), 1)

    def test_fixture_cli_report_only(self):
        self.assertEqual(audit.main([str(self.root / "examples/review-plan.json"), "--fail-on", "none", "--format", "json"]), 0)

    def test_fixture_cli_high_exit_two(self):
        self.assertEqual(audit.main([str(self.root / "examples/review-plan.json"), "--fail-on", "high"]), 2)

    def test_safe_cli_zero(self):
        self.assertEqual(audit.main([str(self.root / "examples/safe-plan.json")]), 0)

    def test_labels_bound_and_sanitized(self):
        self.assertEqual(len(audit.clean_label("z" * 500)), 160)
        self.assertNotIn("\n", audit.clean_label("\nA"))


if __name__ == "__main__":
    unittest.main()
