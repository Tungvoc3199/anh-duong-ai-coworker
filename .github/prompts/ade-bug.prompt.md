---
description: "Find and apply ADE-OS bug knowledge-base guidance for a symptom without treating generic guidance as a proven cause."
name: ade-bug
argument-hint: "Bug symptom or search terms"
agent: ad-diagnose
tools: [read, search, execute]
---
Search the ADE bug knowledge base for `$ARGUMENTS`, then diagnose read-only against live evidence as relevant. Distinguish documented FACT / INFERENCE / PROPOSAL from incident-specific FACT / INFERENCE / UNKNOWN. Do not edit, restart services, expose secrets, alter Core configuration, or claim a root cause from a KB match alone.
