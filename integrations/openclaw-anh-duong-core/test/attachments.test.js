import assert from "node:assert/strict";
import test from "node:test";

import { normalizeInboundAttachmentFacts } from "../src/attachments.js";

const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

test("prefers canonical v2026.7.1 event.media facts", () => {
  assert.deepEqual(
    normalizeInboundAttachmentFacts(
      {
        media: [
          {
            path: "/tmp/openclaw/inbound/canonical.docx",
            url: "media://telegram/canonical-1",
            contentType: DOCX_MIME,
            kind: "document",
            messageId: "canonical-msg",
            workspaceDir: "/tmp/openclaw/inbound",
          },
        ],
        metadata: {
          mediaPath: "/tmp/openclaw/inbound/legacy-wrong.pdf",
          mediaUrl: "media://telegram/legacy-wrong",
          mediaType: "application/pdf",
        },
        messageId: "event-msg",
      },
      { messageId: "ctx-msg" },
    ),
    [
      {
        index: 0,
        kind: "document",
        content_type: DOCX_MIME,
        filename: "canonical.docx",
        local_ref: "/tmp/openclaw/inbound/canonical.docx",
        provider_ref: "media://telegram/canonical-1",
        staged: true,
        source_message_id: "canonical-msg",
      },
    ],
  );
});

test("canonical originalMedia stays provider-side while staging is pending", () => {
  assert.deepEqual(
    normalizeInboundAttachmentFacts({
      originalMedia: [
        {
          path: "/provider/not-local/pending.docx",
          url: "media://telegram/pending-1",
          contentType: DOCX_MIME,
          kind: "document",
          messageId: "pending-msg",
        },
      ],
      mediaStagingPending: true,
      messageId: "event-msg",
    }),
    [
      {
        index: 0,
        kind: "document",
        content_type: DOCX_MIME,
        provider_ref: "media://telegram/pending-1",
        staged: false,
        source_message_id: "pending-msg",
      },
    ],
  );
});

test("pending original media metadata without URL does not expose provider path", () => {
  const [fact] = normalizeInboundAttachmentFacts({
    metadata: {
      originalMediaPaths: ["/provider/not-local/pending.docx"],
      originalMediaTypes: [DOCX_MIME],
      mediaStagingPending: true,
    },
    messageId: "pending-msg",
  });

  assert.equal(fact.kind, "document");
  assert.equal(fact.content_type, DOCX_MIME);
  assert.equal(fact.staged, false);
  assert.equal(fact.source_message_id, "pending-msg");
  assert.equal("provider_ref" in fact, false);
  assert.equal("local_ref" in fact, false);
});

test("normalizes legacy media metadata as compatibility fallback", () => {
  assert.deepEqual(
    normalizeInboundAttachmentFacts(
      {
        metadata: {
          mediaPaths: ["/tmp/openclaw/inbound/a.docx"],
          mediaUrls: ["media://telegram/file-1"],
          mediaTypes: [DOCX_MIME],
          mediaStagingPending: false,
        },
        messageId: "42",
      },
      { messageId: "42" },
    ),
    [
      {
        index: 0,
        kind: "document",
        content_type: DOCX_MIME,
        filename: "a.docx",
        local_ref: "/tmp/openclaw/inbound/a.docx",
        provider_ref: "media://telegram/file-1",
        staged: true,
        source_message_id: "42",
      },
    ],
  );
});

test("supports legacy single media fields and classifies image audio video pdf", () => {
  const cases = [
    ["image/jpeg", "image"],
    ["audio/ogg", "audio"],
    ["video/mp4", "video"],
    ["application/pdf", "document"],
  ];
  for (const [mediaType, kind] of cases) {
    const [fact] = normalizeInboundAttachmentFacts({
      metadata: { mediaPath: "/tmp/file.bin", mediaType },
      messageId: "m1",
    });
    assert.equal(fact.kind, kind);
  }
});

test("caps legacy attachment count and does not invent staged local refs", () => {
  const mediaUrls = Array.from({ length: 12 }, (_, index) => `media://remote/${index}`);
  const facts = normalizeInboundAttachmentFacts({
    metadata: {
      mediaUrls,
      mediaTypes: Array(12).fill("application/octet-stream"),
      mediaStagingPending: true,
    },
    messageId: "m2",
  });

  assert.equal(facts.length, 10);
  assert.equal(facts[0].kind, "file");
  assert.equal(facts[0].staged, false);
  assert.equal("local_ref" in facts[0], false);
});
