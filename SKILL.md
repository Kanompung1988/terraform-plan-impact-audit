---
name: terraform-plan-impact-audit
description: Review saved Terraform plan JSON offline for delete and replacement ordering, provider drift, failed plan checks and removed outputs before apply. Use when a coding agent needs deterministic change-impact triage without uploading or printing sensitive plan values.
license: MIT
compatibility: Python 3.10+ standard library; local `terraform show -json <saved-plan>` output only. No network, Terraform CLI execution, or cloud access performed by the scanner.
metadata:
  author: AREAZERO Skill Lab
  version: "1.0.0"
---

# Review Terraform plan impact safely

## Trigger
Use before approving a Terraform deployment when a **saved plan** and a `terraform show -json tfplan` export are available. Particularly appropriate for large change sets, deletes, resource replacements and root-output compatibility reviews.

## Non-trigger
Do not use to parse raw binary `tfplan`, Terraform state/JSON UI event streams, discover secrets, predict real downtime, validate IAM policy or prove infrastructure correctness. Do not run `terraform apply` automatically.

## Procedure
1. Generate a saved plan in a controlled workspace: `terraform plan -out=tfplan`; then export using `terraform show -json tfplan > tfplan.json`. **HashiCorp warns this JSON may contain secret values in cleartext.** Keep the export private, out of Git, CI artifacts and user-facing chat.
2. Run `python scripts/audit.py tfplan.json --format markdown --fail-on high` locally. The tool reads up to 10 MB and emits resource addresses with instance keys masked, but **never emits** `before`, `after`, `variables`, `planned_values`, check diagnostic text, or raw sensitive fields.
3. Examine TP001–TP007 findings in [rule reference](references/RULES.md). A create-before-destroy replacement can still fail due to quotas or uniqueness restrictions. Distinguish the Terraform plan action from an assurance about eventual outcomes.
4. Compare potential data loss and unexpected drift with an approved migration/backup plan, get human sign-off for destructive actions, and rerun on the exact approved plan export. Never apply or modify cloud resources as part of this skill.
5. Record only rule IDs, sanitized locations, CI exit code, report timestamp and what remains unverified. Do not attach the sensitive input JSON.

## Tests and examples
`python scripts/audit.py examples/safe-plan.json --format json --fail-on high` exits **0**; `python scripts/audit.py examples/review-plan.json --format markdown --fail-on high` exits **2** and describes a synthetic intentional delete/replace. `--fail-on none` reports findings with exit **0**; exit **1** means invalid or unsafe input. Run `python -m unittest discover -s tests -v` to verify implementation.

## Safety and boundaries
Static, offline JSON metadata triage only; the original plan still exists on disk and can contain secrets. This tool does not eliminate that risk, cannot infer exact real-world blast radius, and does not inspect provider-specific semantics, data backups or change approval. Addresses can reveal system names even when instance keys are redacted, so review reports before sharing. See [primary sources](references/SOURCES.md).
