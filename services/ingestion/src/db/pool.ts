/**
 * PostgreSQL connection pooling.
 */

import { Pool, type PoolClient } from 'pg';
import type { AppConfig } from '../config/env.js';

/** Postgres SQLSTATE for a unique constraint violation. */
const UNIQUE_VIOLATION = '23505';

/**
 * Create a connection pool.
 *
 * Sets a server-side `statement_timeout` so a pathological query cannot pin a
 * connection indefinitely, which is the storage half of "the service should
 * not hang". The HTTP half is Fastify's `requestTimeout`.
 */
export function createPool(config: AppConfig): Pool {
  const pool = new Pool({
    connectionString: config.databaseUrl,
    max: config.dbPoolMax,
    // Cap on waiting for a free client. Without it a request queues forever
    // once the pool is saturated, outliving the HTTP request that wanted it.
    connectionTimeoutMillis: config.connectionTimeoutMs,
    // Server-side cap on a single query, enforced by Postgres itself, so it
    // still applies if the client stops waiting.
    statement_timeout: config.dbStatementTimeoutMs,
  });

  // `pg` re-emits errors from idle clients on the pool. This fires when the
  // server closes a connection out from under us, which is routine, but an
  // unhandled 'error' event terminates the process. No pino logger exists at
  // pool construction, so this goes to stderr, which Docker captures.
  pool.on('error', (error) => {
    console.error('idle postgres client error', error);
  });

  return pool;
}

/**
 * Run `fn` inside a transaction, committing on success and rolling back on
 * any thrown error.
 *
 * Always releases the client, including when the rollback itself fails.
 *
 * @throws Whatever `fn` throws, after the rollback completes.
 */
export async function withTransaction<T>(
  pool: Pool,
  fn: (client: PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool.connect();
  // Passed to `release` to decide whether the client goes back in the pool or
  // is destroyed.
  let brokenBy: Error | true | undefined;
  try {
    await client.query('BEGIN');
    const result = await fn(client);
    await client.query('COMMIT');
    return result;
  } catch (error) {
    try {
      await client.query('ROLLBACK');
    } catch (rollbackError) {
      // The rollback failing means the connection state is unknown, so the
      // client must not be reused with a transaction possibly still open.
      // The caller's error is the one worth propagating; this one is handed
      // to `release` so `pg` discards the client and logs it.
      brokenBy = rollbackError instanceof Error ? rollbackError : true;
    }
    throw error;
  } finally {
    client.release(brokenBy);
  }
}

/**
 * True if the error is Postgres' unique-violation (SQLSTATE 23505).
 *
 * Used to distinguish an expected duplicate from a real storage failure.
 */
export function isUniqueViolation(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    (error as { code?: unknown }).code === UNIQUE_VIOLATION
  );
}
