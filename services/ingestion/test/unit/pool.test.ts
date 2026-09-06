/**
 * Pool construction and error classification.
 *
 * `withTransaction` is covered by the repository suite, which drives it
 * through the pg doubles. What is left here is the pool's operational
 * configuration — the timeouts that stop a query pinning a connection — and
 * the SQLSTATE check that tells a duplicate apart from a real failure.
 *
 * No database: `pg` connects lazily, so the settings can be read back off the
 * pool without opening anything.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Pool } from 'pg';
import { createPool, isUniqueViolation } from '../../src/db/pool.js';
import { buildTestConfig } from '../helpers/fakes.js';

let pool: Pool | null = null;

afterEach(async () => {
  await pool?.end().catch(() => {});
  pool = null;
  vi.restoreAllMocks();
});

describe('createPool', () => {
  it('applies the configured pool size', () => {
    pool = createPool(buildTestConfig({ dbPoolMax: 7 }));

    expect(pool.options.max).toBe(7);
  });

  it('caps how long a request waits for a free client', () => {
    /**
     * Without it a request queues forever once the pool is saturated,
     * outliving the HTTP request that wanted it.
     */
    pool = createPool(buildTestConfig({ connectionTimeoutMs: 1234 }));

    expect(pool.options.connectionTimeoutMillis).toBe(1234);
  });

  it('sets a server-side statement timeout', () => {
    /**
     * Enforced by Postgres itself, so it still applies once the client has
     * stopped waiting for the answer.
     */
    pool = createPool(buildTestConfig({ dbStatementTimeoutMs: 4321 }));

    expect(
      (pool.options as { statement_timeout?: number }).statement_timeout,
    ).toBe(4321);
  });

  it('opens no connection until one is asked for', () => {
    pool = createPool(buildTestConfig());

    expect(pool.totalCount).toBe(0);
  });

  it('survives an idle client error instead of taking the process down', () => {
    /**
     * `pg` re-emits errors from idle clients on the pool, and an unhandled
     * 'error' event on an EventEmitter terminates Node. The server closing a
     * connection out from under an idle pool is routine.
     */
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
    pool = createPool(buildTestConfig());

    expect(() => pool?.emit('error', new Error('connection terminated'))).not.toThrow();
    expect(logged).toHaveBeenCalled();
  });
});

describe('isUniqueViolation', () => {
  it('recognises the unique-violation SQLSTATE', () => {
    expect(isUniqueViolation({ code: '23505' })).toBe(true);
  });

  it('rejects a neighbouring integrity violation', () => {
    // 23503 is foreign_key_violation: a genuine failure, not a duplicate, and
    // treating it as one would silently drop the event.
    expect(isUniqueViolation({ code: '23503' })).toBe(false);
  });

  it.each([
    ['null', null],
    ['undefined', undefined],
    ['a plain string', 'unique violation'],
    ['an error without a code', new Error('boom')],
    ['a numeric code', { code: 23505 }],
  ])('rejects %s', (_label, candidate) => {
    expect(isUniqueViolation(candidate)).toBe(false);
  });
});
