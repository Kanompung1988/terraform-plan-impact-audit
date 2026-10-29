# Terraform plan-impact rules

| Rule | Level | Bounded signal | Practical follow-up |
|---|---|---|---|
| TP001 | HIGH | resource `actions == ["delete"]` | Confirm data retention/backup and change approval. |
| TP002 | HIGH | `actions == ["delete","create"]` | Destruction occurs before recreation; review downtime and dependencies. |
| TP003 | MEDIUM | `actions == ["create","delete"]` | Check quotas/uniqueness and eventual destroy order. |
| TP004 | MEDIUM | non-noop `resource_drift` | Investigate external state changes; may be expected. |
| TP005 | HIGH | failed `checks[]` status | Verify failed assertions/conditions; diagnostic messages deliberately omitted. |
| TP006 | MEDIUM | removed root output | Check downstream consumers and automation. |
| TP007 | LOW | root output new/updated value contains `after_unknown: true` | Inspect plan-time unknown dependencies. |

`replace_paths`, `after_sensitive`, `before_sensitive`, provider-specific access control and concrete values are deliberately not printed. Counts are based on `resource_changes`; drift is reviewed separately and may overlap. The tool refuses unknown multi-action sequences and future JSON-major versions rather than returning a misleading green result. Findings are engineering review prompts, not vulnerability proof.
