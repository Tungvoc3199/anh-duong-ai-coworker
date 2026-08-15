import { basename } from "node:path";

const MAX_ATTACHMENTS = 10;
const MAX_CONTENT_TYPE = 255;
const MAX_FILENAME = 512;
const MAX_REF = 2048;
const MAX_MESSAGE_ID = 128;
const MAX_TRANSCRIPT = 8000;
const MAX_SUMMARY = 8000;
const ATTACHMENT_KINDS = new Set([
  "image",
  "audio",
  "video",
  "document",
  "file",
  "unknown",
]);

function boundedString(value, maxLength) {
  if (typeof value !== "string") {
    return undefined;
  }
  const normalized = value.trim();
  if (!normalized) {
    return undefined;
  }
  return normalized.slice(0, maxLength);
}

function stringArray(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item) => typeof item === "string" && item.trim().length > 0);
}

function classifyKind(contentType) {
  const value = typeof contentType === "string" ? contentType.toLowerCase() : "";
  if (value.startsWith("image/")) return "image";
  if (value.startsWith("audio/")) return "audio";
  if (value.startsWith("video/")) return "video";
  if (
    value === "application/pdf" ||
    value === "application/msword" ||
    value.startsWith("application/vnd.openxmlformats-officedocument") ||
    value.startsWith("application/vnd.ms-") ||
    value.startsWith("application/vnd.oasis.opendocument")
  ) {
    return "document";
  }
  return value ? "file" : "unknown";
}

function normalizedKind(kind, contentType) {
  const supplied = boundedString(kind, 32)?.toLowerCase();
  if (supplied && ATTACHMENT_KINDS.has(supplied)) {
    return supplied;
  }
  return classifyKind(contentType);
}

function filenameFromPath(localRef) {
  if (typeof localRef !== "string" || localRef.length === 0) {
    return undefined;
  }
  return boundedString(basename(localRef), MAX_FILENAME);
}

function objectArray(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (item) => item && typeof item === "object" && !Array.isArray(item),
  );
}

function normalizeCanonicalFacts(items, event, ctx, { locallyStaged }) {
  return items.slice(0, MAX_ATTACHMENTS).map((item, index) => {
    const contentType = boundedString(item.contentType, MAX_CONTENT_TYPE);
    const localRef = locallyStaged ? boundedString(item.path, MAX_REF) : undefined;
    const providerRef = boundedString(item.url, MAX_REF);
    const filename = locallyStaged ? filenameFromPath(localRef) : undefined;
    const transcript = boundedString(item.transcript, MAX_TRANSCRIPT);
    const contentSummary = boundedString(
      item.contentSummary ?? item.content_summary,
      MAX_SUMMARY,
    );
    const sourceMessageId = boundedString(
      item.messageId ?? event?.messageId ?? ctx?.messageId,
      MAX_MESSAGE_ID,
    );

    return {
      index,
      kind: normalizedKind(item.kind, contentType),
      ...(contentType ? { content_type: contentType } : {}),
      ...(filename ? { filename } : {}),
      ...(localRef ? { local_ref: localRef } : {}),
      ...(providerRef ? { provider_ref: providerRef } : {}),
      ...(transcript ? { transcript } : {}),
      ...(contentSummary ? { content_summary: contentSummary } : {}),
      staged: Boolean(localRef),
      ...(sourceMessageId ? { source_message_id: sourceMessageId } : {}),
    };
  });
}

function normalizeLegacyFacts(event, ctx) {
  const metadata =
    event?.metadata && typeof event.metadata === "object" && !Array.isArray(event.metadata)
      ? event.metadata
      : {};

  const paths = stringArray(metadata.mediaPaths);
  const urls = stringArray(metadata.mediaUrls);
  const types = stringArray(metadata.mediaTypes);

  const singlePath = boundedString(metadata.mediaPath, MAX_REF);
  const singleUrl = boundedString(metadata.mediaUrl, MAX_REF);
  const singleType = boundedString(metadata.mediaType, MAX_CONTENT_TYPE);

  if (paths.length === 0 && singlePath) paths.push(singlePath);
  if (urls.length === 0 && singleUrl) urls.push(singleUrl);
  if (types.length === 0 && singleType) types.push(singleType);

  const count = Math.min(MAX_ATTACHMENTS, Math.max(paths.length, urls.length, types.length));
  if (count === 0) {
    return [];
  }

  const sourceMessageId = boundedString(
    event?.messageId ?? ctx?.messageId,
    MAX_MESSAGE_ID,
  );
  const stagingPending = metadata.mediaStagingPending === true;
  const facts = [];

  for (let index = 0; index < count; index += 1) {
    const localRef = boundedString(paths[index], MAX_REF);
    const providerRef = boundedString(urls[index], MAX_REF);
    const contentType = boundedString(types[index], MAX_CONTENT_TYPE);
    const filename = filenameFromPath(localRef);
    const fact = {
      index,
      kind: classifyKind(contentType),
      ...(contentType ? { content_type: contentType } : {}),
      ...(filename ? { filename } : {}),
      ...(localRef ? { local_ref: localRef } : {}),
      ...(providerRef ? { provider_ref: providerRef } : {}),
      staged: Boolean(localRef) && !stagingPending,
      ...(sourceMessageId ? { source_message_id: sourceMessageId } : {}),
    };
    facts.push(fact);
  }

  return facts;
}

function normalizePendingOriginalMetadataFacts(event, ctx) {
  const metadata =
    event?.metadata && typeof event.metadata === "object" && !Array.isArray(event.metadata)
      ? event.metadata
      : {};

  const paths = stringArray(metadata.originalMediaPaths);
  const urls = stringArray(metadata.originalMediaUrls);
  const types = stringArray(metadata.originalMediaTypes);

  const singlePath = boundedString(metadata.originalMediaPath, MAX_REF);
  const singleUrl = boundedString(metadata.originalMediaUrl, MAX_REF);
  const singleType = boundedString(metadata.originalMediaType, MAX_CONTENT_TYPE);

  if (paths.length === 0 && singlePath) paths.push(singlePath);
  if (urls.length === 0 && singleUrl) urls.push(singleUrl);
  if (types.length === 0 && singleType) types.push(singleType);

  const count = Math.min(MAX_ATTACHMENTS, Math.max(paths.length, urls.length, types.length));
  if (count === 0) {
    return [];
  }

  const sourceMessageId = boundedString(
    event?.messageId ?? ctx?.messageId,
    MAX_MESSAGE_ID,
  );

  return Array.from({ length: count }, (_item, index) => {
    const providerRef = boundedString(urls[index], MAX_REF);
    const contentType = boundedString(types[index], MAX_CONTENT_TYPE);
    return {
      index,
      kind: classifyKind(contentType),
      ...(contentType ? { content_type: contentType } : {}),
      ...(providerRef ? { provider_ref: providerRef } : {}),
      staged: false,
      ...(sourceMessageId ? { source_message_id: sourceMessageId } : {}),
    };
  });
}

export function normalizeInboundAttachmentFacts(event, ctx = {}) {
  const stagedMedia = objectArray(event?.media);
  if (stagedMedia.length > 0) {
    return normalizeCanonicalFacts(stagedMedia, event, ctx, { locallyStaged: true });
  }

  if (event?.mediaStagingPending === true) {
    const originalMedia = objectArray(event?.originalMedia);
    if (originalMedia.length > 0) {
      return normalizeCanonicalFacts(originalMedia, event, ctx, {
        locallyStaged: false,
      });
    }
  }

  const metadataStagingPending =
    event?.mediaStagingPending === true || event?.metadata?.mediaStagingPending === true;
  if (metadataStagingPending) {
    const pendingOriginalMetadata = normalizePendingOriginalMetadataFacts(event, ctx);
    if (pendingOriginalMetadata.length > 0) {
      return pendingOriginalMetadata;
    }
  }

  return normalizeLegacyFacts(event, ctx);
}
