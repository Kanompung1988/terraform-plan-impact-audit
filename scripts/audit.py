#!/usr/bin/env python3
"""Offline, values-blind review of Terraform 'terraform show -json <plan>' output."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 10_000_000
MAX_CHANGES = 20_000
SEVERITIES = {"high": 3, "medium": 2, "low": 1}
RULES = {
    "TP001": ("high", "Resource deletion", "Confirm retention, backup, data impact and approval before apply."),
    "TP002": ("high", "Destroy-first replacement", "Review downtime/data impact, dependencies, and replacement ordering."),
    "TP003": ("medium", "Create-first replacement", "Check quotas, uniqueness constraints, cutover and eventual destruction."),
    "TP004": ("medium", "Provider drift", "Compare intended configuration with out-of-band changes before apply."),
    "TP005": ("high", "Failed plan check", "Fix the failed check before relying on or applying this plan."),
    "TP006": ("medium", "Root output removed", "Check consumers of this output before removing it."),
    "TP007": ("low", "Unknown planned output", "Confirm dependent consumers tolerate an unknown value at plan time."),
}


def clean_label(value: object) -> str:
    """Emit only bounded address labels, never plan values; mask for_each instance keys."""
    if not isinstance(value, str):
        return "<unnamed>"
    # Terraform resource addresses may embed untrusted user-supplied for_each keys.
    value = re.sub(r"\[[^\]\n]*\]", "[*]", value)
    value = re.sub(r"[^A-Za-z0-9_.*/@:\[\]-]", "?", value)
    return value[:160] or "<unnamed>"


def make_finding(rule: str, where: str) -> dict[str, str]:
    level, title, recommendation = RULES[rule]
    return {"rule": rule, "severity": level, "location": clean_label(where),
            "title": title, "recommendation": recommendation}


def is_unknown(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, dict):
        return any(is_unknown(x) for x in value.values())
    if isinstance(value, list):
        return any(is_unknown(x) for x in value)
    return False


def analyze(doc: object) -> dict:
    if not isinstance(doc, dict):
        raise ValueError("expected JSON object from terraform show -json <saved plan>")
    fmt = doc.get("format_version")
    if not isinstance(fmt, str) or not re.match(r"^1\.\d+$", fmt):
        raise ValueError("unsupported Terraform JSON format_version (expected 1.x)")
    if "resource_changes" not in doc or not isinstance(doc["resource_changes"], list):
        raise ValueError("expected resource_changes: this must be a plan, not a state or UI event stream")
    changes = doc["resource_changes"]
    if len(changes) > MAX_CHANGES:
        raise ValueError("too many resource changes")
    findings: list[dict[str, str]] = []
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "no-op": 0, "read": 0}
    for row in changes:
        if not isinstance(row, dict) or not isinstance(row.get("change"), dict):
            raise ValueError("malformed resource_changes entry")
        address = clean_label(row.get("address", "resource"))
        actions = row["change"].get("actions")
        if not isinstance(actions, list) or not actions or any(not isinstance(a, str) or a not in counts for a in actions):
            raise ValueError("invalid actions in resource_changes entry")
        if actions == ["no-op"]:
            counts["no-op"] += 1
        elif actions == ["delete", "create"]:
            counts["replace"] += 1
            findings.append(make_finding("TP002", address))
        elif actions == ["create", "delete"]:
            counts["replace"] += 1
            findings.append(make_finding("TP003", address))
        elif actions == ["delete"]:
            counts["delete"] += 1
            findings.append(make_finding("TP001", address))
        elif len(actions) == 1:
            counts[actions[0]] += 1
        else:
            raise ValueError("unsupported multi-action change; refusing partial risk assessment")
    drift = doc.get("resource_drift", [])
    if not isinstance(drift, list) or len(drift) > MAX_CHANGES:
        raise ValueError("invalid resource_drift list")
    for row in drift:
        if not isinstance(row, dict) or not isinstance(row.get("change"), dict):
            raise ValueError("malformed resource_drift entry")
        acts = row["change"].get("actions")
        if not isinstance(acts, list):
            raise ValueError("invalid resource_drift actions")
        if acts != ["no-op"]:
            findings.append(make_finding("TP004", row.get("address", "drift")))
    checks = doc.get("checks", [])
    if not isinstance(checks, list):
        raise ValueError("invalid checks list")
    for index, row in enumerate(checks):
        if not isinstance(row, dict):
            raise ValueError("malformed check entry")
        if row.get("status") == "fail":
            # Never include arbitrary check diagnostics: may contain secret values.
            findings.append(make_finding("TP005", f"check-{index+1}"))
    outputs = doc.get("output_changes", {})
    if not isinstance(outputs, dict):
        raise ValueError("invalid output_changes object")
    for name, row in sorted(outputs.items()):
        if not isinstance(row, dict) or not isinstance(row.get("change"), dict):
            raise ValueError("malformed output_changes entry")
        change = row["change"]
        actions = change.get("actions", [])
        if actions == ["delete"]:
            findings.append(make_finding("TP006", "output." + clean_label(name)))
        if actions in (["create"], ["update"]) and is_unknown(change.get("after_unknown")):
            findings.append(make_finding("TP007", "output." + clean_label(name)))
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (order[f["severity"]], f["rule"], f["location"]))
    return {"tool": "terraform-plan-impact-audit", "format_version": fmt,
            "counts": counts, "findings": findings,
            "safety": "Resource addresses only (instance keys masked). Values, variables and sensitive fields are never emitted."}


def read_plan(path: Path) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError("input must be a regular non-symlink JSON plan file")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("plan JSON exceeds 10 MB cap")
    with path.open("rb") as fh:
        return json.load(fh)


def render_markdown(result: dict) -> str:
    lines = ["# Terraform plan impact audit", "", f"Findings: {len(result['findings'])}", "",
             "| Severity | Rule | Location | Review action |", "|---|---|---|---|"]
    for f in result["findings"]:
        loc = f["location"].replace("|", "\\|")
        lines.append(f"| {f['severity'].upper()} | {f['rule']} | `{loc}` | {f['recommendation']} |")
    lines.extend(["", result["safety"]])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", type=Path, help="saved `terraform show -json tfplan` output, not raw binary plan")
    p.add_argument("--format", choices=("json", "markdown"), default="markdown")
    p.add_argument("--fail-on", choices=("high", "medium", "low", "none"), default="high")
    args = p.parse_args(argv)
    try:
        result = analyze(read_plan(args.plan))
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        print(f"Invalid Terraform plan input: {type(error).__name__}: {str(error)[:150]}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.format == "json" else render_markdown(result))
    if args.fail_on != "none" and any(SEVERITIES[f["severity"]] >= SEVERITIES[args.fail_on] for f in result["findings"]):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
