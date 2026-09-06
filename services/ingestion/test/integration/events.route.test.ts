/**
 * End-to-end event submission against real PostgreSQL.
 *
 * This is where the requirements that depend on database semantics are
 * actually proven: idempotency, out-of-order tolerance, and the auth boundary.
 */

import { describe, it } from 'vitest';

describe('POST /v1/events', () => {
  it.todo(
    'stores a new event and answers 201 created',
    // Assert the response body and that exactly one events row exists.
  );

  it.todo(
    'answers 200 duplicate on a replay of the same event_id',
    // 200 rather than 409: from an at-least-once agent's perspective a replay
    // succeeded, and 409 would push clients toward treating retries as errors.
  );

  it.todo(
    'keeps exactly one row after a replay',
    // The idempotency requirement stated as a row count, which is the
    // assertion that would actually catch a regression.
  );

  it.todo(
    'ignores a changed payload on a replay',
    // ON CONFLICT DO NOTHING means the first write wins. Assert the stored
    // payload is still the original, since silently accepting a rewrite would
    // let a client mutate history through the idempotency key.
  );

  it.todo(
    'stores exactly one row when the same event is submitted concurrently',
    // Fire N identical requests in parallel. This is the race that an
    // application-level SELECT-then-INSERT would lose and the unique index
    // wins.
  );

  it.todo('persists raw byte-identically to the submitted body');

  it.todo('persists a normalised payload alongside raw');

  it.todo('records client_id from the API key, not the body');

  it.todo(
    'accepts events whose occurred_at is older than an already-stored event',
    // The out-of-order requirement: assert both rows exist and that the late
    // event received the higher ingest_seq despite the earlier timestamp.
    // That ordering is precisely what lets the analyser find it.
  );

  it.todo('creates the agent row on first sight');

  it.todo('advances agents.last_seen_at on a newer event');

  it.todo(
    'does not rewind agents.last_seen_at on an out-of-order older event',
    // GREATEST in the upsert.
  );

  it.todo(
    'moves agents.first_seen_at backwards for an event predating it',
    // LEAST in the upsert.
  );

  it.todo('answers 401 when the Authorization header is absent');

  it.todo('answers 401 for an unknown key');

  it.todo(
    'returns an identical body for a missing and a wrong key',
    // The response must not tell an attacker which half of the credential was
    // wrong.
  );

  it.todo('writes nothing when authentication fails');

  it.todo('answers 400 with field issues for a malformed envelope');

  it.todo('answers 400 for a body that is not valid JSON');

  it.todo(
    'answers 413 for a body over BODY_LIMIT_BYTES',
    // Build the app with a small limit rather than sending 512 KB.
  );

  it.todo(
    'accepts a body just under the limit',
    // The complement, so the limit is not accidentally off by a large margin.
  );

  it.todo(
    'answers 503 when the database is unreachable',
    // Assert the body is generic and the connection detail was logged, not
    // returned.
  );

  it.todo('never echoes the submitted payload in an error response');
});

describe('POST /v1/events/batch', () => {
  it.todo('stores every event in a fully new batch and answers 207');

  it.todo('reports a mix of created and duplicate across the batch');

  it.todo('collapses a repeated event_id within one batch to a single row');

  it.todo(
    'stores the valid entries and reports the invalid ones by index',
    // Per-item validation: one bad event must not discard the whole batch.
  );

  it.todo('answers 400 when events is empty');

  it.todo('answers 400 when the batch exceeds maxBatchSize');

  it.todo(
    'persists nothing when the transaction fails partway',
    // All-or-nothing within a batch, so a client retrying a failed batch
    // cannot end up with a partial write it does not know about.
  );

  it.todo('answers 401 without a valid key');
});
