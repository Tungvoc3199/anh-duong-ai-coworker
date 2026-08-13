import assert from "node:assert/strict";
import test from "node:test";

import { normalizeInboundAttachmentFacts } from "../src/attachments.js";

test("normalizes v2026.7.1 message_received media metadata", () => {
  assert.deepEqual(
    normalizeInboundAttachmentFacts(
      {
        metadata: {
          mediaPaths: ["/tmp/openclaw/inbound/a.docx"],
          mediaUrls: ["media://telegram/file-1"],
          mediaTypes: [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          ],
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
        content_type:
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename: "a.docx",
        local_ref: "/tmp/openclaw/inbound/a.docx",
        provider_ref: "media://telegram/file-1",
        staged: true,
        source_message_id: "42",
      },
    ],
  );
});

test("supports single media fields and classifies image audio video pdf", () => {
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

test("caps attachment count and does not invent staged local refs", () => {
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
