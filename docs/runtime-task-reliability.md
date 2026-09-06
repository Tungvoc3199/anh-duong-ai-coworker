# Runtime task reliability repair

Baseline: Core a55fcc3; gateway OpenClaw 2026.9.2 replychain ed3bf622-r2.
Incident: run_5091536973124c06b7b0882da877f147; final Telegram message 5627.

FACT: owner consent worked. The task had approval_required=false and the owner constraint.
FACT: Core was healthy and ready over both host-local and configured gateway consumer paths.
FACT: executor workspace mapping recognized only the retired /mnt/f/AIOS/anh-duong-core root.
The actual /home/thadc/AIOS/anh-duong-core was sent unchanged into the container.
Docker mounts source at /workspaces/anh-duong-core; the host-shaped path inside the container
contains only the separately mounted .git. This is not evidence of host repository corruption.
FACT: generic instructions did not distinguish host and container service/process observations.
FACT: DoD requires criterion_verification objects, but instructions allowed a free-text final.
The incident returned Markdown evidence; the parser kept it only as summary. OutcomeJudge
correctly rejected missing structured evidence. Parsing a fenced JSON result had the same defect.
FACT: completed actions are not blindly replayed when evidence is missing. Keep that behavior.
FACT: operator.read denials affected a CLI status subcall; permitted health probes still work.
A missing scope means that subcall was unavailable, not that Core was stopped.

Repair:
- Map current and legacy Core host roots to the existing gateway source mount.
- Preserve unrelated path prefixes and existing access boundaries.
- Supply explicit host/container scope, configured Core endpoint discovery and separate health checks.
- Require one JSON result for DoD tasks; keep the summary in the user's language.
- Accept a single whole-response JSON fence without interpreting arbitrary prose as evidence.
- Core remains responsible for verification and Telegram delivery.

Evidence:
- RED reproduces current-root mapping and fenced evidence failures.
- Targeted suite: 63 passed.
- Real read-only gateway/model canary: resp_6157d070-ded6-4817-8881-cf0c3e9c5f15.
  Correct Core /health and /ready HTTP 200; separate OpenClaw health; two structured criteria.
- Actual OutcomeJudge on this canary: satisfied / dod_satisfied.
- This canary is NOT Telegram E2E and did not deploy the candidate.
- Full regression: 1378 passed in 248.56s. Changed-file lint and diff check: PASS.

Remaining boundaries:
- No blanket guarantee for all task types. Writing, research, media and recovery require their
  own outcome evidence; permission restrictions must be reported accurately.
- Old delivery dead letters were not resent or deleted.
- The running gateway image and plugin may be owned by another active repair lane: do not replace.
- Production Core cutover requires authorized system-service control; a previous ordinary-user
  restart was rejected with Interactive authentication required. Do not work around it.
- After cutover require consumer path verification and one fresh real Telegram outcome.
