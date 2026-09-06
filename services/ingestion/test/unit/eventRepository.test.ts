/**
 * Repository behaviour against a mocked pg pool.
 *
 * Narrow by design. The real SQL is covered by the integration suite against
 * actual Postgres; mocking a driver only proves the mock behaves as configured.
 * What is worth asserting here is the parameter mapping and the error
 * translation, neither of which needs a database.
 */

import type { Pool } from 'pg';
import { describe, expect, it } from 'vitest';
import { PgEventRepository } from '../../src/db/eventRepository.js';
import { StorageError, type AgentEvent } from '../../src/domain/types.js';
import { FakePgPool, eventInsertResponder, type QueryResponder } from '../helpers/fakes.js';

/** A persistable event, overridable per test. */
function buildEvent(overrides: Partial<AgentEvent> = {}): AgentEvent {
  return {
    eventId: 'evt-1',
    agentId: 'agent-alpha',
    occurredAt: new Date('2026-08-25T12:00:00Z'),
    type: 'file_read',
    payload: { path: '/home/alpha/notes.txt' },
    raw: { event_id: 'evt-1', payload: { path: '/home/alpha/notes.txt' } },
    tags: ['audit'],
    clientId: 'test-client',
    ...overrides,
  };
}

/** Repository wired to a fake pool, with both handed back for assertions. */
function withFakePool(responder?: QueryResponder) {
  const pool = new FakePgPool(responder);
  // The fake implements only the surface the repository touches, so the cast
  // is confined to this one helper.
  return { pool, repository: new PgEventRepository(pool as unknown as Pool) };
}

describe('PgEventRepository.insertIfAbsent', () => {
  it('reports created when the insert returns a row', async () => {
    // ON CONFLICT DO NOTHING with RETURNING yields zero rows on conflict, so
    // rowCount is how a duplicate is detected.
    const { repository } = withFakePool(eventInsertResponder(['evt-1']));

    expect(await repository.insertIfAbsent(buildEvent())).toStrictEqual({
      eventId: 'evt-1',
      status: 'created',
    });
  });

  it('reports duplicate when the insert returns no rows', async () => {
    const { repository } = withFakePool(eventInsertResponder([]));

    expect(await repository.insertIfAbsent(buildEvent())).toStrictEqual({
      eventId: 'evt-1',
      status: 'duplicate',
    });
  });

  it('passes event fields as positional parameters in schema order', async () => {
    // Catches a silent column reorder that would otherwise write a url into
    // the path column.
    const { pool, repository } = withFakePool(eventInsertResponder(['evt-1']));
    const event = buildEvent();

    await repository.insertIfAbsent(event);

    expect(pool.client.find('INSERT INTO events')?.values).toStrictEqual([
      event.eventId,
      event.agentId,
      event.occurredAt,
      event.type,
      event.payload,
      event.raw,
      event.tags,
      event.clientId,
    ]);
  });

  it('hands payload and raw to the driver as objects for jsonb adaptation', async () => {
    // Not pre-stringified: `pg` adapts a plain object to jsonb, and a manual
    // JSON.stringify would store a quoted string instead.
    const { pool, repository } = withFakePool(eventInsertResponder(['evt-1']));
    const event = buildEvent();

    await repository.insertIfAbsent(event);

    const values = pool.client.find('INSERT INTO events')?.values ?? [];
    expect(values[4]).toStrictEqual(event.payload);
    expect(values[5]).toStrictEqual(event.raw);
    expect(typeof values[4]).toBe('object');
  });

  it('passes tags as a native array, not a JSON string', async () => {
    const { pool, repository } = withFakePool(eventInsertResponder(['evt-1']));

    await repository.insertIfAbsent(buildEvent({ tags: ['audit', 'sensitive'] }));

    expect(pool.client.find('INSERT INTO events')?.values[6]).toStrictEqual(['audit', 'sensitive']);
  });

  it('runs the agent upsert and the event insert in one transaction', async () => {
    const { pool, repository } = withFakePool(eventInsertResponder(['evt-1']));

    await repository.insertIfAbsent(buildEvent());

    expect(pool.client.statements).toStrictEqual(['BEGIN', 'INSERT', 'INSERT', 'COMMIT']);
    // The agent must be upserted first: events.agent_id is a foreign key.
    expect(pool.client.queries[1]?.text).toContain('INSERT INTO agents');
    expect(pool.client.queries[2]?.text).toContain('INSERT INTO events');
  });

  it('rolls back and wraps the driver error in a StorageError', async () => {
    const driverError = new Error('connection reset by peer');
    const { pool, repository } = withFakePool((query) => {
      if (query.text.includes('INSERT INTO events')) {
        throw driverError;
      }
      return { rowCount: 1, rows: [{}] };
    });

    const thrown = await repository.insertIfAbsent(buildEvent()).catch((error: unknown) => error);

    expect(thrown).toBeInstanceOf(StorageError);
    expect((thrown as StorageError).cause).toBe(driverError);
    expect(pool.client.statements).toContain('ROLLBACK');
    expect(pool.client.statements).not.toContain('COMMIT');
  });

  it('releases the client even when the rollback itself fails', async () => {
    // A leaked connection under repeated failure exhausts the pool and turns
    // a transient outage into a permanent one.
    const rollbackError = new Error('rollback failed');
    const { pool, repository } = withFakePool((query) => {
      if (query.text.includes('INSERT INTO events')) {
        throw new Error('insert failed');
      }
      if (query.text.startsWith('ROLLBACK')) {
        throw rollbackError;
      }
      return { rowCount: 1, rows: [{}] };
    });

    await expect(repository.insertIfAbsent(buildEvent())).rejects.toBeInstanceOf(StorageError);

    expect(pool.client.releases).toHaveLength(1);
    // Released with the rollback error, which tells `pg` to discard the client
    // rather than return it to the pool with a transaction still open.
    expect(pool.client.releases[0]).toBe(rollbackError);
  });

  it('releases the client on success', async () => {
    const { pool, repository } = withFakePool(eventInsertResponder(['evt-1']));

    await repository.insertIfAbsent(buildEvent());

    expect(pool.client.releases).toStrictEqual([undefined]);
  });
});

describe('PgEventRepository.insertBatchIfAbsent', () => {
  it('returns one result per input event, in input order', async () => {
    const { repository } = withFakePool(eventInsertResponder(['evt-1', 'evt-2', 'evt-3']));

    const results = await repository.insertBatchIfAbsent([
      buildEvent({ eventId: 'evt-1' }),
      buildEvent({ eventId: 'evt-2' }),
      buildEvent({ eventId: 'evt-3' }),
    ]);

    expect(results.map((result) => result.eventId)).toStrictEqual(['evt-1', 'evt-2', 'evt-3']);
    expect(results.every((result) => result.status === 'created')).toBe(true);
  });

  it('returns an empty array without touching the pool for an empty batch', async () => {
    const { pool, repository } = withFakePool();

    expect(await repository.insertBatchIfAbsent([])).toStrictEqual([]);
    expect(pool.connectCount).toBe(0);
  });

  it('collapses duplicate event ids within the batch', async () => {
    // ON CONFLICT cannot resolve two conflicting rows inside one statement,
    // so the repeat must be removed before the query runs.
    const { pool, repository } = withFakePool(eventInsertResponder(['evt-1']));

    await repository.insertBatchIfAbsent([
      buildEvent({ eventId: 'evt-1' }),
      buildEvent({ eventId: 'evt-1' }),
    ]);

    const eventInserts = pool.client.queries.filter((query) =>
      query.text.includes('INSERT INTO events'),
    );
    expect(eventInserts).toHaveLength(1);
  });

  it('reports the collapsed within-batch repeat as duplicate', async () => {
    const { repository } = withFakePool(eventInsertResponder(['evt-1']));

    const results = await repository.insertBatchIfAbsent([
      buildEvent({ eventId: 'evt-1' }),
      buildEvent({ eventId: 'evt-1' }),
    ]);

    expect(results).toStrictEqual([
      { eventId: 'evt-1', status: 'created' },
      { eventId: 'evt-1', status: 'duplicate' },
    ]);
  });

  it('reports a mix of created and duplicate correctly', async () => {
    const { repository } = withFakePool(eventInsertResponder(['evt-new']));

    const results = await repository.insertBatchIfAbsent([
      buildEvent({ eventId: 'evt-known' }),
      buildEvent({ eventId: 'evt-new' }),
    ]);

    expect(results).toStrictEqual([
      { eventId: 'evt-known', status: 'duplicate' },
      { eventId: 'evt-new', status: 'created' },
    ]);
  });

  it('persists nothing when the transaction fails', async () => {
    const { pool, repository } = withFakePool((query) => {
      if (query.text.includes('INSERT INTO events') && query.values[0] === 'evt-2') {
        throw new Error('insert failed');
      }
      return { rowCount: 1, rows: [{}] };
    });

    await expect(
      repository.insertBatchIfAbsent([
        buildEvent({ eventId: 'evt-1' }),
        buildEvent({ eventId: 'evt-2' }),
      ]),
    ).rejects.toBeInstanceOf(StorageError);

    expect(pool.client.statements).toContain('ROLLBACK');
    expect(pool.client.statements).not.toContain('COMMIT');
  });
});

describe('PgEventRepository.upsertAgentSeen', () => {
  it('inserts an unknown agent', async () => {
    const { pool, repository } = withFakePool();
    const seenAt = new Date('2026-08-25T12:00:00Z');

    await repository.upsertAgentSeen('agent-alpha', seenAt);

    expect(pool.client.find('INSERT INTO agents')?.values).toStrictEqual(['agent-alpha', seenAt]);
  });

  it('never moves last_seen_at backwards', async () => {
    // The guarantee lives in the SQL, so this asserts the statement rather
    // than the outcome; the integration suite proves the behaviour against
    // real Postgres.
    const { pool, repository } = withFakePool();

    await repository.upsertAgentSeen('agent-alpha', new Date('2026-08-25T12:00:00Z'));

    const upsert = pool.client.find('INSERT INTO agents')?.text ?? '';
    expect(upsert).toContain('GREATEST(agents.last_seen_at, EXCLUDED.last_seen_at)');
    expect(upsert).toContain('LEAST(agents.first_seen_at, EXCLUDED.first_seen_at)');
  });

  it('wraps a failure to acquire a client in a StorageError', async () => {
    const { pool, repository } = withFakePool();
    pool.failConnectWith = new Error('pool exhausted');

    await expect(repository.upsertAgentSeen('agent-alpha', new Date())).rejects.toBeInstanceOf(
      StorageError,
    );
  });
});

describe('PgEventRepository.healthCheck', () => {
  it('returns true when the probe query succeeds', async () => {
    const { repository } = withFakePool();

    expect(await repository.healthCheck()).toBe(true);
  });

  it('returns false rather than throwing when the query fails', async () => {
    // Lets /readyz answer 503 instead of 500.
    const { repository } = withFakePool(() => {
      throw new Error('database is gone');
    });

    expect(await repository.healthCheck()).toBe(false);
  });

  it('returns false rather than throwing when the pool refuses to connect', async () => {
    const { pool, repository } = withFakePool();
    pool.failConnectWith = new Error('Cannot use a pool after calling end on the pool');

    expect(await repository.healthCheck()).toBe(false);
  });
});
