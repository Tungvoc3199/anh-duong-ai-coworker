# ADE-OS v1

ADE-OS is workspace tooling for evidence-led Copilot coordination. It is independent
of Core runtime code, the runtime database, provider routing, and dependencies.

## Commands

Run `/home/thadc/AIOS/anh-duong-core/.venv/bin/python scripts/ade_os.py --help` from the repository root.

- `index` creates a deterministic project file/hash index.
- `memory -- <read-only-cli> ...` runs an explicitly supplied external runtime-memory
  CLI with a five-second timeout; errors fail closed and output is redacted.
- `bugs [query]` lists or AND-searches the Markdown knowledge base in `bugs/`.
- `route <text>` selects an agent deterministically from `.ade-os/routing-rules.yaml`.
- `gate close --evidence evidence.json` blocks closure unless conflict, diff, test,
  backup, rollback, and independent `review: "PASS"` evidence are all present.
- `report --input report.json` writes evidence using the configured artifact path and
  falls back to local state when that path is unavailable.

`.ade-os/*.yaml` deliberately contains JSON, a YAML subset, so standard-library JSON
parsing is sufficient. Do not use these tools to mutate Core runtime or its database.
