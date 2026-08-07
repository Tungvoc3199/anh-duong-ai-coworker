---
description: "Use when: any command, file change, service operation, database operation, or secret could affect safety."
applyTo: "**"
---
# Safety rules

- Never run `git reset --hard`, `git clean -fd`, `git checkout -- .`, broad `rm -rf`, destructive SQL, force-push, history rewrite, or service stop/disable unless the user explicitly scopes and approves it.
- Never print tokens, API keys, passwords, cookies, Authorization headers, private keys, or raw secret-bearing configuration.
- Never edit or delete the runtime DB, migrations, provider routing, or model configuration outside approved scope.
- Never overwrite an existing customization without a timestamped backup.
- Keep scope narrow. Do not install dependencies or refactor unrelated code without approval.
- If evidence is incomplete, stop and report BLOCKED/UNKNOWN rather than guessing.
