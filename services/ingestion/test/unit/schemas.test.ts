/**
 * Envelope validation.
 *
 * The service's first line of defence: everything here runs before any
 * database work, so a malformed body is rejected cheaply.
 */

import { describe, it } from 'vitest';

describe('parseEnvelope', () => {
  it.todo(
    'accepts a well-formed envelope and maps it to an AgentEvent',
    // Arrange: a valid file_read envelope, clientId "test-client".
    // Act: parseEnvelope(body, 'test-client').
    // Assert: ok is true; eventId, agentId, type match; occurredAt is a Date
    // equal to the input instant; clientId comes from the argument.
  );

  it.todo(
    'takes clientId from the argument, not the body',
    // A body carrying its own client_id must not override the authenticated
    // identity, or a client could forge attribution for another tenant.
  );

  it.todo(
    'rejects a missing event_id',
    // Assert: ok is false and issues contains a path of 'event_id'.
  );

  it.todo('rejects a blank event_id');

  it.todo('rejects a missing agent_id');

  it.todo(
    'rejects a timestamp with no timezone offset',
    // '2026-08-25T12:00:00' is ambiguous. Accepting it would silently corrupt
    // the ordering the timeline and the rapid-reads rule depend on.
  );

  it.todo('rejects a non-ISO timestamp such as "yesterday"');

  it.todo(
    'accepts a timestamp with a non-UTC offset and normalises it',
    // '2026-08-25T14:00:00+02:00' is unambiguous; assert occurredAt equals
    // 12:00:00Z.
  );

  it.todo(
    'accepts an unknown event type and stores its payload verbatim',
    // Agents gain capabilities faster than this service deploys, so an
    // unrecognised type must not be a rejection.
  );

  it.todo(
    'validates a known type against its payload schema',
    // A file_read with no path is a client bug worth reporting, not a
    // passthrough. Assert the issue path is 'payload.path'.
  );

  it.todo(
    'preserves unrecognised fields inside a known payload',
    // Passthrough, so the analyser can use a field before ingestion knows it.
  );

  it.todo(
    'sets raw to the exact submitted body',
    // Assert raw deep-equals the input even where payload was normalised.
    // This is the forensic-fidelity guarantee.
  );

  it.todo('defaults tags to an empty array when absent');

  it.todo('rejects more than 50 tags');

  it.todo('rejects a payload that is not an object');

  it.todo('reports every failing field at once, not just the first');
});

describe('toValidationError', () => {
  it.todo('flattens nested zod paths into dotted strings');

  it.todo(
    'never includes submitted values in the issue text',
    // Payloads routinely carry secrets and this output reaches both the
    // response and the logs.
  );
});
