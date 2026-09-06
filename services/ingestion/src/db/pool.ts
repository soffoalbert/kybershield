/**
 * PostgreSQL connection pooling.
 */

import { Pool, type PoolClient } from 'pg';
import type { AppConfig } from '../config/env.js';

/**
 * Create a connection pool.
 *
 * Sets a server-side `statement_timeout` so a pathological query cannot pin a
 * connection indefinitely, which is the storage half of "the service should
 * not hang". The HTTP half is Fastify's `requestTimeout`.
 */
export function createPool(config: AppConfig): Pool {
  throw new Error('TODO: implement createPool');
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
  throw new Error('TODO: implement withTransaction');
}

/**
 * True if the error is Postgres' unique-violation (SQLSTATE 23505).
 *
 * Used to distinguish an expected duplicate from a real storage failure.
 */
export function isUniqueViolation(error: unknown): boolean {
  throw new Error('TODO: implement isUniqueViolation');
}
