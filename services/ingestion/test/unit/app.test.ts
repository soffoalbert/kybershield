/**
 * Routes, auth, and error mapping with no database.
 *
 * The integration suite proves the SQL; this proves the HTTP contract, and it
 * proves the parts a real database cannot produce on demand: an unexpected
 * exception escaping a handler, a zod error thrown rather than returned, and a
 * body over the size limit.
 *
 * The recurring assertion is that no response echoes the request body. Event
 * payloads carry credentials, so an error that quotes the offending value
 * turns the error channel into a leak.
 */

import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { StorageError } from '../../src/domain/types.js';
import {
  FakeApiKeyStore,
  FakeEventRepository,
  buildEnvelope,
  buildTestApp,
} from '../helpers/fakes.js';

const AUTH = { authorization: 'Bearer test-key' };
const SECRET = 'super-secret-value';

describe('POST /v1/events', () => {
  it('answers 201 created for a new event', async () => {
    const { app, repository } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope({ event_id: 'evt-new' }),
    });

    expect(response.statusCode).toBe(201);
    expect(response.json()).toStrictEqual({ eventId: 'evt-new', status: 'created' });
    expect(repository.events.has('evt-new')).toBe(true);
  });

  it('answers 200 duplicate on a replay', async () => {
    const { app } = await buildTestApp();
    const payload = buildEnvelope({ event_id: 'evt-replay' });
    await app.inject({ method: 'POST', url: '/v1/events', headers: AUTH, payload });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload,
    });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toStrictEqual({ eventId: 'evt-replay', status: 'duplicate' });
  });

  it('takes client_id from the API key rather than the body', async () => {
    const { app, repository } = await buildTestApp();

    await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope({ event_id: 'evt-client', client_id: 'impersonated' }),
    });

    expect(repository.events.get('evt-client')?.clientId).toBe('test-client');
  });

  it('answers 400 with field paths for a malformed envelope', async () => {
    const { app } = await buildTestApp();
    const { event_id: _omitted, ...missingEventId } = buildEnvelope();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: missingEventId,
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().error).toBe('validation_failed');
    expect(response.json().issues).toContainEqual(
      expect.objectContaining({ path: 'event_id' }),
    );
  });

  it('names the nested field when a payload is the wrong shape', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope({ type: 'file_read', payload: { path: 42 } }),
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().issues).toContainEqual(
      expect.objectContaining({ path: 'payload.path' }),
    );
  });

  it('writes nothing when validation fails', async () => {
    const { app, repository } = await buildTestApp();

    await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope({ event_id: '' }),
    });

    expect(repository.events.size).toBe(0);
  });
});

describe('authentication', () => {
  it('answers 401 without an Authorization header', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      payload: buildEnvelope(),
    });

    expect(response.statusCode).toBe(401);
    expect(response.json()).toStrictEqual({ error: 'unauthorized' });
  });

  it('answers 401 for an unknown key', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: { authorization: 'Bearer nope' },
      payload: buildEnvelope(),
    });

    expect(response.statusCode).toBe(401);
  });

  it('does not distinguish a missing key from a wrong one', async () => {
    const { app } = await buildTestApp();

    const missing = await app.inject({
      method: 'POST',
      url: '/v1/events',
      payload: buildEnvelope(),
    });
    const wrong = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: { authorization: 'Bearer nope' },
      payload: buildEnvelope(),
    });

    // An attacker must not learn which half of their credential was accepted.
    expect(missing.statusCode).toBe(wrong.statusCode);
    expect(missing.json()).toStrictEqual(wrong.json());
  });

  it('rejects a key presented without the Bearer scheme', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: { authorization: 'test-key' },
      payload: buildEnvelope(),
    });

    expect(response.statusCode).toBe(401);
  });

  it('resolves a second configured key to its own client', async () => {
    const keys = new Map([
      ['key-one', 'client-one'],
      ['key-two', 'client-two'],
    ]);
    const { app, repository } = await buildTestApp({
      apiKeyStore: new FakeApiKeyStore(keys),
    });

    await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: { authorization: 'Bearer key-two' },
      payload: buildEnvelope({ event_id: 'evt-two' }),
    });

    expect(repository.events.get('evt-two')?.clientId).toBe('client-two');
  });

  it('leaves the health probes unauthenticated', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({ method: 'GET', url: '/healthz' });

    expect(response.statusCode).toBe(200);
  });
});

describe('error mapping', () => {
  it('answers 503 storage_unavailable for a StorageError', async () => {
    const repository = new FakeEventRepository();
    repository.failWith = new StorageError('Failed to insert event', new Error('ECONNREFUSED'));
    const { app } = await buildTestApp({ repository });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope(),
    });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toStrictEqual({ error: 'storage_unavailable' });
  });

  it('does not leak the driver error behind a 503', async () => {
    const repository = new FakeEventRepository();
    // A real driver error quotes the connection string, which carries the
    // database password.
    repository.failWith = new StorageError(
      'insert failed',
      new Error('postgres://user:hunter2@db:5432/kybershield'),
    );
    const { app } = await buildTestApp({ repository });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope(),
    });

    expect(response.body).not.toContain('hunter2');
  });

  it('answers 500 with a generic body for an unexpected error', async () => {
    const repository = new FakeEventRepository();
    repository.failWith = new Error('a bug nobody anticipated');
    const { app } = await buildTestApp({ repository });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope(),
    });

    expect(response.statusCode).toBe(500);
    expect(response.json()).toStrictEqual({ error: 'internal_server_error' });
    expect(response.body).not.toContain('a bug nobody anticipated');
  });

  it('maps a thrown ZodError to the same 400 shape as a returned one', async () => {
    /**
     * `parseEnvelope` returns its failures rather than throwing, so this
     * branch exists for a zod schema used anywhere else in a handler. The
     * contract a client sees must not depend on which layer rejected the
     * request.
     */
    const repository = new FakeEventRepository();
    repository.failWith = new z.ZodError([
      {
        code: 'custom',
        path: ['payload', 'path'],
        message: 'not a path',
      },
    ]);
    const { app } = await buildTestApp({ repository });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope(),
    });

    expect(response.statusCode).toBe(400);
    expect(response.json()).toStrictEqual({
      error: 'validation_failed',
      issues: [{ path: 'payload.path', message: 'not a path' }],
    });
  });

  it('answers 400 invalid_json for a body that is not JSON', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: { ...AUTH, 'content-type': 'application/json' },
      payload: '{not json at all}',
    });

    expect(response.statusCode).toBe(400);
    expect(response.json()).toStrictEqual({ error: 'invalid_json' });
  });

  it('answers 413 for a body over the configured limit', async () => {
    const { app } = await buildTestApp({ config: { bodyLimitBytes: 1024 } });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events',
      headers: AUTH,
      payload: buildEnvelope({ payload: { path: 'x'.repeat(2048) } }),
    });

    expect(response.statusCode).toBe(413);
    expect(response.json()).toStrictEqual({ error: 'payload_too_large' });
  });

  it('answers 404 with JSON for an unknown route', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({ method: 'GET', url: '/nope' });

    expect(response.statusCode).toBe(404);
    expect(response.json()).toStrictEqual({ error: 'not_found' });
  });

  it('never echoes the submitted payload in an error response', async () => {
    const repository = new FakeEventRepository();
    repository.failWith = new Error('boom');
    const { app } = await buildTestApp({ repository });

    for (const url of ['/v1/events', '/v1/events/batch']) {
      const payload =
        url === '/v1/events'
          ? buildEnvelope({ payload: { path: SECRET } })
          : { events: [buildEnvelope({ payload: { path: SECRET } })] };

      const response = await app.inject({ method: 'POST', url, headers: AUTH, payload });

      expect(response.body).not.toContain(SECRET);
    }
  });
});

describe('POST /v1/events/batch', () => {
  it('answers 207 with one result per submitted entry', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: {
        events: [buildEnvelope({ event_id: 'b-1' }), buildEnvelope({ event_id: 'b-2' })],
      },
    });

    expect(response.statusCode).toBe(207);
    expect(response.json()).toStrictEqual({
      results: [
        { eventId: 'b-1', status: 'created' },
        { eventId: 'b-2', status: 'created' },
      ],
      accepted: 2,
      duplicates: 0,
      rejected: [],
    });
  });

  it('reports invalid entries by their submitted index', async () => {
    const { app, repository } = await buildTestApp();
    const { event_id: _omitted, ...invalid } = buildEnvelope();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: {
        events: [invalid, buildEnvelope({ event_id: 'b-good' }), invalid],
      },
    });

    const body = response.json();
    // Indexes are what maps a failure back to the submitted array, since
    // `results` only covers the entries that were stored.
    expect(body.rejected.map((entry: { index: number }) => entry.index)).toStrictEqual([0, 2]);
    expect(body.results).toStrictEqual([{ eventId: 'b-good', status: 'created' }]);
    expect(repository.events.size).toBe(1);
  });

  it('counts duplicates separately from acceptances', async () => {
    const { app } = await buildTestApp();
    const event = buildEnvelope({ event_id: 'b-dup' });
    await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: { events: [event] },
    });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: { events: [event, buildEnvelope({ event_id: 'b-fresh' })] },
    });

    expect(response.json().accepted).toBe(1);
    expect(response.json().duplicates).toBe(1);
  });

  it('answers 400 when events is missing', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: {},
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().error).toBe('validation_failed');
  });

  it('answers 400 when events is not an array', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: { events: { event_id: 'not-an-array' } },
    });

    expect(response.statusCode).toBe(400);
  });

  it('answers 400 when events is empty', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: { events: [] },
    });

    expect(response.statusCode).toBe(400);
  });

  it('answers 400 and stores nothing when the batch exceeds the maximum', async () => {
    const { app, repository } = await buildTestApp({ config: { maxBatchSize: 2 } });

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: AUTH,
      payload: {
        events: [
          buildEnvelope({ event_id: 'o-1' }),
          buildEnvelope({ event_id: 'o-2' }),
          buildEnvelope({ event_id: 'o-3' }),
        ],
      },
    });

    expect(response.statusCode).toBe(400);
    expect(response.json().issues[0].message).toContain('at most 2');
    // All-or-nothing on the envelope check: nothing is stored, so the caller
    // can resubmit the whole batch split in two.
    expect(repository.events.size).toBe(0);
  });

  it('answers 401 without a valid key and stores nothing', async () => {
    const { app, repository } = await buildTestApp();

    const response = await app.inject({
      method: 'POST',
      url: '/v1/events/batch',
      headers: { authorization: 'Bearer nope' },
      payload: { events: [buildEnvelope()] },
    });

    expect(response.statusCode).toBe(401);
    expect(repository.events.size).toBe(0);
  });
});

describe('GET /readyz', () => {
  it('reports ready when the repository is healthy', async () => {
    const { app } = await buildTestApp();

    const response = await app.inject({ method: 'GET', url: '/readyz' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toStrictEqual({ status: 'ready', database: true });
  });

  it('reports degraded when the repository is not', async () => {
    const repository = new FakeEventRepository();
    repository.healthy = false;
    const { app } = await buildTestApp({ repository });

    const response = await app.inject({ method: 'GET', url: '/readyz' });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toStrictEqual({ status: 'degraded', database: false });
  });

});
