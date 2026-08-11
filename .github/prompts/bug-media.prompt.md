---
description: "Diagnose Telegram media and image pipeline from ingestion through multimodal provider payload to Core response."
name: bug-media
argument-hint: "Media failure or correlation evidence"
agent: ad-deep-debug
tools: [read, search, execute]
---
Trace `$ARGUMENTS`: `Telegram ingestion → OpenClaw media-understanding → provider/model → multimodal payload → Core classification → response`. Verify MIME, caption/envelope parsing, image-capability declaration, fallback, identity/state correlation, direct/workflow route, and Task/Run creation. No provider change or real media send without scope approval. Redact all credentials.