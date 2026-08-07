---
description: "Diagnose provider authentication, authorization, quota, model availability, OAuth, API key, and 401/403/429 failures safely."
name: bug-provider-auth
argument-hint: "Provider error and redacted context"
agent: ad-diagnose
tools: [read, search, execute]
---
Diagnose `$ARGUMENTS` without exposing credentials. Classify 401/403/429, OAuth refresh, API-key presence (never value), quota, account authorization, provider/model availability, and verified fallback. Redact secrets in all output/artifacts. Return evidence and the next safe action; do not rotate secrets or change providers without approval.