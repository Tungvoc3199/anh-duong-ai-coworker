# Owner request consent

Direct Telegram user turns from the configured owner count as consent for the current requested goal.
Set ANH_DUONG_OWNER_TELEGRAM_ID to the numeric owner ID already verified in OpenClaw commands.ownerAllowFrom.
Unset the variable to retain the existing approval behavior.

The gateway supplies source_origin=telegram_user only for native trigger=user, a UUID run ID,
and populated native sender/chat/session identity. Prompt text and recent-message queues never
grant provenance. Core compares the actor hash with the configured owner. Unknown/synthetic turns
retain existing gates. DENY, forbidden risk, and other escalation decisions are not overridden.
Project constraints cannot mint the reserved owner-consent marker. Existing pending approvals
are not automatically resolved. Consent does not authorize unrequested side effects.

OpenClaw 9.2 source declares inbound runId but deriveInboundMessageHookContext does not populate it.
Use native agent hook identity instead; do not infer identity from an absent inbound field.
Keep the existing native reply-chain overlay and image revision plugin baseline.

Rollout order: back up config and release pointer; install Core release; configure owner; restart
Core and require health/ready; install the two changed plugin source files; restart gateway with
the same image; run scripts/verify_openclaw_core_path.py against configured gateway Core URL.
Then require a real owner Telegram inbound, Core prepare with owner.direct_request, model response,
outbound message ID, and clean prepare logs. Until then this checkpoint is not CLOSED.

Rollback: restore prior plugin files, owner configuration and Core release pointer; restart affected
services with the supported service account; repeat Core path verification. Do not use privilege
escalation to work around a rejected service-control operation.
