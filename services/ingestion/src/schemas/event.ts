/**
 * Request body schemas for event submission.
 *
 * Validation runs before any database work so a malformed body costs nothing
 * beyond parsing, which is part of how the service avoids hanging on bad
 * input.
 *
 * The envelope is strict about the fields it owns (`event_id`, `agent_id`,
 * `timestamp`, `type`) and permissive about `payload`, because agents evolve
 * faster than this service deploys. Per-type payload schemas below are used to
 * *normalise* known types, not to reject unknown ones.
 */

import { z } from 'zod';
import type { AgentEvent, Result, ValidationError } from '../domain/types.js';

/**
 * ISO-8601 UTC timestamp.
 *
 * Rejects timestamps without an explicit offset: a naive timestamp from an
 * agent in an unknown timezone would silently corrupt the event ordering that
 * the timeline and the rapid-reads rule depend on.
 */
export const Iso8601Utc = z
  .string()
  .datetime({ offset: true })
  .describe('ISO-8601 timestamp with an explicit UTC offset');

/** The common envelope every event shares, regardless of type. */
export const EventEnvelopeSchema = z.object({
  event_id: z.string().min(1).max(200),
  agent_id: z.string().min(1).max(200),
  timestamp: Iso8601Utc,
  type: z.string().min(1).max(100),
  payload: z.record(z.unknown()),
  tags: z.array(z.string().min(1).max(100)).max(50).optional(),
});

export type EventEnvelope = z.infer<typeof EventEnvelopeSchema>;

/** Batch submission body. */
export const EventBatchSchema = z.object({
  events: z.array(EventEnvelopeSchema).min(1).max(100),
});

// --- Known payload shapes -------------------------------------------------
// `.passthrough()` on each: unrecognised fields are preserved rather than
// stripped, since the analyser may learn to use them before this service does.

export const HttpRequestPayload = z
  .object({
    method: z.string().min(1),
    url: z.string().min(1),
    headers: z.record(z.string()).optional(),
    body_size: z.number().int().nonnegative().optional(),
  })
  .passthrough();

export const FileReadPayload = z
  .object({
    path: z.string().min(1),
  })
  .passthrough();

export const ShellCommandPayload = z
  .object({
    command: z.string().min(1),
  })
  .passthrough();

export const ToolCallPayload = z
  .object({
    name: z.string().min(1),
    args: z.record(z.unknown()).optional(),
  })
  .passthrough();

/**
 * Payload schema by event type.
 *
 * A type absent from this map is accepted with its payload stored verbatim.
 */
export const PAYLOAD_SCHEMAS: Record<string, z.ZodTypeAny> = {
  http_request: HttpRequestPayload,
  file_read: FileReadPayload,
  shell_command: ShellCommandPayload,
  tool_call: ToolCallPayload,
};

/**
 * Validate one request body and convert it into a persistable event.
 *
 * Returns a `Result` instead of throwing so the batch endpoint can report
 * per-item failures without aborting the whole request.
 *
 * Behaviour:
 * - Envelope validated against {@link EventEnvelopeSchema}.
 * - If `type` is known, `payload` is validated against its schema; a mismatch
 *   is a validation failure, not a silent passthrough.
 * - If `type` is unknown, `payload` is kept as-is.
 * - `raw` is set to the untouched input body, so the original submission
 *   survives even when normalisation changes `payload`.
 * - `tags` defaults to an empty array.
 *
 * @param body Parsed JSON body, untrusted.
 * @param clientId Authenticated client, taken from the auth layer rather than
 *   the body so a client cannot forge attribution.
 */
export function parseEnvelope(
  body: unknown,
  clientId: string,
): Result<AgentEvent, ValidationError> {
  const envelope = EventEnvelopeSchema.safeParse(body);
  if (!envelope.success) {
    return { ok: false, error: toValidationError(envelope.error) };
  }

  const { event_id, agent_id, timestamp, type, payload, tags } = envelope.data;

  let normalised = payload;
  const payloadSchema = PAYLOAD_SCHEMAS[type];
  if (payloadSchema) {
    const parsed = payloadSchema.safeParse(payload);
    if (!parsed.success) {
      // Re-rooted under `payload` so the reported path matches the submitted
      // body rather than the sub-schema's own coordinates.
      return { ok: false, error: toValidationError(parsed.error, ['payload']) };
    }
    normalised = parsed.data as Record<string, unknown>;
  }

  return {
    ok: true,
    value: {
      // The wire format is snake_case; the domain entity is camelCase. This
      // mapping is the only place the two meet.
      eventId: event_id,
      agentId: agent_id,
      occurredAt: new Date(timestamp),
      type,
      payload: normalised,
      raw: body as Record<string, unknown>,
      tags: tags ?? [],
      // From the auth layer, never the body, so a client cannot forge it.
      clientId,
    },
  };
}

/**
 * Convert a zod error into flat, loggable field issues.
 *
 * Deliberately reports paths and messages only. Submitted values are never
 * included, because event payloads routinely carry secrets and this output
 * lands in both the response and the logs.
 *
 * @param pathPrefix Prepended to every issue path, so an error from a nested
 *   schema can be reported relative to the whole body.
 */
export function toValidationError(
  error: z.ZodError,
  pathPrefix: readonly (string | number)[] = [],
): ValidationError {
  return {
    issues: error.issues.map((issue) => ({
      path: [...pathPrefix, ...issue.path].join('.'),
      message: issue.message,
    })),
  };
}
