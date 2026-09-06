/**
 * End-to-end event submission against real PostgreSQL.
 *
 * This is where the requirements that depend on database semantics are
 * actually proven: idempotency, out-of-order tolerance, and the auth boundary.
 *
 * Requests go through `app.inject()` rather than a socket, so the suite needs
 * a database but never a listening port.
 */

import type { FastifyInstance } from 'fastify';
import { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import {
  TEST_API_KEY,
  TEST_CLIENT_ID,
  TEST_DATABASE_URL,
  buildIntegrationApp,
  countRows,
  createTestPool,
  fetchAgent,
  fetchEvent,
  truncateAll,
} from './setup.js';

// Top-level await so the suite can be skipped at collection time with a clear
// reason, rather than failing every test with a connection error.
let pool: Pool | null = null;
let unavailable = '';
try {
  pool = await createTestPool();
} catch (error) {
  unavailable = error instanceof Error ? error.message : String(error);
  console.warn(`skipping ingestion integration suite: ${unavailable}`);
}

afterAll(async () => {
  await pool?.end();
});

const AGENT_ID = 'agent-alpha';
const AUTH = { authorization: `Bearer ${TEST_API_KEY}` };

/** A valid envelope, with any field overridable by the test under way. */
function buildEvent(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    event_id: 'evt-default',
    agent_id: AGENT_ID,
    timestamp: new Date().toISOString(),
    type: 'file_read',
    payload: { path: '/home/alpha/notes.txt' },
    ...overrides,
  };
}

const describeDb = pool ? describe : describe.skip;

describeDb('POST /v1/events', () => {
  const db = pool as Pool;
  let app: FastifyInstance;

  beforeAll(async () => {
    app = await buildIntegrationApp(db);
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    await truncateAll(db);
  });

  /** Submit one envelope with the valid key. */
  function post(payload: unknown, headers: Record<string, string> = AUTH) {
    return app.inject({ method: 'POST', url: '/v1/events', headers, payload: payload as object });
  }

  it('stores a new event and answers 201 created', async () => {
    const response = await post(buildEvent({ event_id: 'abc123' }));

    expect(response.statusCode).toBe(201);
    expect(response.json()).toStrictEqual({ eventId: 'abc123', status: 'created' });
    expect(await countRows(db, 'events')).toBe(1);
  });

  it('answers 200 duplicate on a replay of the same event_id', async () => {
    const event = buildEvent({ event_id: 'dup123' });
    await post(event);

    const response = await post(event);

    expect(response.statusCode).toBe(200);
    expect(response.json()).toStrictEqual({ eventId: 'dup123', status: 'duplicate' });
  });

  it('keeps exactly one row after a replay', async () => {
    const event = buildEvent({ event_id: 'replay-one-row' });

    await post(event);
    await post(event);

    expect(await countRows(db, 'events')).toBe(1);
  });

  it('ignores a changed payload on a replay', async () => {
    const first = buildEvent({ event_id: 'idempotent-check', payload: { path: '/original' } });
    await post(first);

    await post({ ...first, payload: { path: '/changed' } });

    const stored = await fetchEvent(db, 'idempotent-check');
    expect(stored?.['payload']).toStrictEqual({ path: '/original' });
  });

  it('stores exactly one row when the same event is submitted concurrently', async () => {
    const event = buildEvent({ event_id: 'concurrent-row' });

    const responses = await Promise.all(Array.from({ length: 8 }, () => post(event)));

    expect(await countRows(db, 'events')).toBe(1);
    // Exactly one caller is told it created the row; the rest see the replay.
    expect(responses.filter((r) => r.statusCode === 201)).toHaveLength(1);
  });

  it('persists raw exactly as submitted', async () => {
    const event = buildEvent({ event_id: 'bytewise', tags: ['audit'] });

    await post(event);

    const stored = await fetchEvent(db, 'bytewise');
    // `raw` is jsonb, so byte-for-byte preservation is not on offer; what
    // matters is that no field was dropped, added, or rewritten.
    expect(stored?.['raw']).toStrictEqual(event);
  });

  it('persists a normalised payload alongside raw', async () => {
    const event = buildEvent({
      event_id: 'normalize123',
      type: 'http_request',
      // `method` and `url` are the known shape; `retries` is not, and
      // passthrough keeps it rather than stripping it.
      payload: { method: 'GET', url: 'https://api.github.com/user', retries: 2 },
    });

    await post(event);

    const stored = await fetchEvent(db, 'normalize123');
    expect(stored?.['payload']).toStrictEqual({
      method: 'GET',
      url: 'https://api.github.com/user',
      retries: 2,
    });
    expect(stored?.['raw']).toStrictEqual(event);
  });

  it('records client_id from the API key, not the body', async () => {
    await post(buildEvent({ event_id: 'client-from-key', client_id: 'malicious' }));

    const stored = await fetchEvent(db, 'client-from-key');
    expect(stored?.['client_id']).toBe(TEST_CLIENT_ID);
  });

  it('accepts events whose timestamp is older than an already-stored event', async () => {
    const now = Date.now();
    await post(
      buildEvent({ event_id: 'out-of-order-1', timestamp: new Date(now + 10_000).toISOString() }),
    );
    await post(
      buildEvent({ event_id: 'out-of-order-2', timestamp: new Date(now - 10_000).toISOString() }),
    );

    const first = await fetchEvent(db, 'out-of-order-1');
    const second = await fetchEvent(db, 'out-of-order-2');

    // ingest_seq follows arrival, not the agent's clock, which is what lets the
    // analyser pick up a late event instead of skipping past it.
    expect(Number(second?.['ingest_seq'])).toBeGreaterThan(Number(first?.['ingest_seq']));
  });

  it('creates the agent row on first sight', async () => {
    await post(buildEvent({ event_id: 'first-seen-agent' }));

    expect(await countRows(db, 'agents')).toBe(1);
  });

  it('advances agents.last_seen_at on a newer event', async () => {
    const older = new Date(Date.now() - 60_000).toISOString();
    const newer = new Date().toISOString();

    await post(buildEvent({ event_id: 'ls-first', timestamp: older }));
    await post(buildEvent({ event_id: 'ls-second', timestamp: newer }));

    const agent = await fetchAgent(db, AGENT_ID);
    expect((agent?.['last_seen_at'] as Date).toISOString()).toBe(newer);
  });

  it('does not rewind agents.last_seen_at on an out-of-order older event', async () => {
    const newer = new Date().toISOString();
    const older = new Date(Date.now() - 10_000).toISOString();

    await post(buildEvent({ event_id: 'ls-new', timestamp: newer }));
    await post(buildEvent({ event_id: 'ls-old', timestamp: older }));

    const agent = await fetchAgent(db, AGENT_ID);
    expect((agent?.['last_seen_at'] as Date).toISOString()).toBe(newer);
  });

  it('moves agents.first_seen_at backwards for an event predating it', async () => {
    const newer = new Date().toISOString();
    const older = new Date(Date.now() - 100_000).toISOString();

    await post(buildEvent({ event_id: 'fs-new', timestamp: newer }));
    await post(buildEvent({ event_id: 'fs-old', timestamp: older }));

    const agent = await fetchAgent(db, AGENT_ID);
    expect((agent?.['first_seen_at'] as Date).toISOString()).toBe(older);
  });

  it('answers 401 when the Authorization header is absent', async () => {
    const response = await post(buildEvent({ event_id: 'auth-none' }), {});

    expect(response.statusCode).toBe(401);
  });

  it('answers 401 for an unknown key', async () => {
    const response = await post(buildEvent({ event_id: 'auth-bad' }), {
      authorization: 'Bearer totally-invalid',
    });

    expect(response.statusCode).toBe(401);
  });

  it('returns an identical body for a missing and a wrong key', async () => {
    const missing = await post(buildEvent({ event_id: 'a' }), {});
    const wrong = await post(buildEvent({ event_id: 'b' }), {
      authorization: 'Bearer totally-wrong',
    });

    expect(missing.json()).toStrictEqual(wrong.json());
  });

  it('writes nothing when authentication fails', async () => {
    await post(buildEvent({ event_id: 'never-write' }), { authorization: 'Bearer fail' });

    expect(await countRows(db, 'events')).toBe(0);
  });

  it('answers 400 with field issues for a malformed envelope', async () => {
    const { event_id, ...missingEventId } = buildEvent();

    const response = await post(missingEventId);

    expect(response.statusCode).toBe(400);
    const body = response.json();
    expect(body.error).toBe('validation_failed');
    expect(body.issues).toContainEqual(
      expect.objectContaining({ path: 'event_id' }),
    );
  });

  it('answers 400 for a body that is not valid JSON', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: { ...AUTH, 'content-type': 'application/json' },
      payload: '{this is not: json}',
    });

    expect(response.statusCode).toBe(400);
    expect(response.json()).toStrictEqual({ error: 'invalid_json' });
  });

  it('never echoes the submitted payload in an error response', async () => {
    const response = await post(
      buildEvent({ event_id: 'echo', payload: { path: 'super-secret-value' } }),
      { authorization: 'Bearer bad' },
    );

    expect(response.statusCode).toBe(401);
    expect(response.body).not.toContain('super-secret-value');
  });
});

describeDb('POST /v1/events body limits', () => {
  const db = pool as Pool;
  const BODY_LIMIT = 2048;
  let app: FastifyInstance;

  beforeAll(async () => {
    // A limit small enough to cross with a readable payload, instead of
    // building a 512 KB body to hit the production default.
    app = await buildIntegrationApp(db, { bodyLimitBytes: BODY_LIMIT });
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    await truncateAll(db);
  });

  it('answers 413 for a body over BODY_LIMIT_BYTES', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEvent({ event_id: 'huge', payload: { path: 'x'.repeat(BODY_LIMIT) } }),
    });

    expect(response.statusCode).toBe(413);
    expect(response.json()).toStrictEqual({ error: 'payload_too_large' });
  });

  it('accepts a body just under the limit', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEvent({ event_id: 'just-under', payload: { path: 'x'.repeat(1700) } }),
    });

    expect(response.statusCode).toBe(201);
  });
});

describeDb('POST /v1/events when the database is unreachable', () => {
  let deadPool: Pool;
  let app: FastifyInstance;

  beforeAll(async () => {
    // Its own pool, closed on purpose: ending the shared one would break every
    // other suite in the file.
    deadPool = new Pool({ connectionString: TEST_DATABASE_URL });
    deadPool.on('error', () => {});
    app = await buildIntegrationApp(deadPool);
    await deadPool.end();
  });

  afterAll(async () => {
    await app.close();
  });

  it('answers 503 storage_unavailable without leaking the driver error', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEvent({ event_id: 'db-down' }),
    });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toStrictEqual({ error: 'storage_unavailable' });
  });

  it('reports readiness as degraded rather than failing the request', async () => {
    const response = await app.inject({ method: 'GET', url: '/readyz' });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toStrictEqual({ status: 'degraded', database: false });
  });
});

describeDb('POST /v1/events/batch', () => {
  const db = pool as Pool;
  let app: FastifyInstance;

  beforeAll(async () => {
    app = await buildIntegrationApp(db);
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    await truncateAll(db);
  });

  /** Submit a batch envelope with the valid key. */
  function postBatch(events: unknown, headers: Record<string, string> = AUTH) {
    return app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers,
      payload: { events } as object,
    });
  }

  it('stores every event in a fully new batch and answers 207', async () => {
    const response = await postBatch([
      buildEvent({ event_id: 'batch-1' }),
      buildEvent({ event_id: 'batch-2' }),
    ]);

    expect(response.statusCode).toBe(207);
    const body = response.json();
    expect(body.results).toHaveLength(2);
    expect(body.accepted).toBe(2);
    expect(body.duplicates).toBe(0);
    expect(await countRows(db, 'events')).toBe(2);
  });

  it('reports a mix of created and duplicate across the batch', async () => {
    await postBatch([buildEvent({ event_id: 'mix-old' })]);

    const response = await postBatch([
      buildEvent({ event_id: 'mix-old' }),
      buildEvent({ event_id: 'mix-new' }),
    ]);

    expect(response.statusCode).toBe(207);
    const body = response.json();
    expect(body.results).toStrictEqual([
      { eventId: 'mix-old', status: 'duplicate' },
      { eventId: 'mix-new', status: 'created' },
    ]);
    expect(body.accepted).toBe(1);
    expect(body.duplicates).toBe(1);
  });

  it('collapses a repeated event_id within one batch to a single row', async () => {
    const event = buildEvent({ event_id: 'dupe-batch' });

    const response = await postBatch([event, { ...event }, { ...event }]);

    expect(response.statusCode).toBe(207);
    expect(await countRows(db, 'events')).toBe(1);
    // One result per submitted entry, so positions still line up for the
    // caller; only the first is reported as created.
    expect(response.json().results).toStrictEqual([
      { eventId: 'dupe-batch', status: 'created' },
      { eventId: 'dupe-batch', status: 'duplicate' },
      { eventId: 'dupe-batch', status: 'duplicate' },
    ]);
  });

  it('stores the valid entries and reports the invalid ones by index', async () => {
    const { event_id, ...missingEventId } = buildEvent();

    const response = await postBatch([buildEvent({ event_id: 'good-batch' }), missingEventId]);

    expect(response.statusCode).toBe(207);
    const body = response.json();
    expect(body.results).toStrictEqual([{ eventId: 'good-batch', status: 'created' }]);
    expect(body.rejected).toHaveLength(1);
    expect(body.rejected[0].index).toBe(1);
    // The valid remainder is still stored: one bad entry must not cost the
    // caller the whole batch.
    expect(await countRows(db, 'events')).toBe(1);
  });

  it('answers 400 when events is empty', async () => {
    const response = await postBatch([]);

    expect(response.statusCode).toBe(400);
    expect(response.json().error).toBe('validation_failed');
  });

  it('answers 400 when the batch exceeds the documented maximum', async () => {
    const oversized = Array.from({ length: 120 }, (_, index) =>
      buildEvent({ event_id: `big-batch-${index}` }),
    );

    const response = await postBatch(oversized);

    expect(response.statusCode).toBe(400);
    expect(await countRows(db, 'events')).toBe(0);
  });

  it('answers 401 without a valid key', async () => {
    const response = await postBatch([buildEvent({ event_id: 'fail-key' })], {
      authorization: 'Bearer wrongkey',
    });

    expect(response.statusCode).toBe(401);
    expect(await countRows(db, 'events')).toBe(0);
  });
});
