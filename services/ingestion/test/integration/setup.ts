/**
 * Integration test harness.
 *
 * Runs against a real PostgreSQL instance, because the interesting behaviour
 * (ON CONFLICT idempotency, GREATEST on last_seen_at, foreign keys, the
 * ingest_seq ordering) lives in the SQL and a mocked driver cannot verify any
 * of it.
 *
 * Start one with `docker compose up -d postgres`.
 */

import { Pool } from 'pg';
import type { FastifyInstance } from 'fastify';

/** Connection string, from TEST_DATABASE_URL or the compose default. */
export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ??
  'postgres://kybershield:kybershield@localhost:5432/kybershield';

/**
 * Open a pool against the test database.
 *
 * Skips the whole suite with a clear message if nothing is listening, so a
 * developer without Docker running sees "start Postgres" instead of a wall of
 * connection errors.
 */
export async function createTestPool(): Promise<Pool> {
  throw new Error('TODO: implement createTestPool');
}

/**
 * Delete all rows and reset the analysis cursor.
 *
 * Truncate with CASCADE rather than dropping the schema, so each test starts
 * clean without paying to re-run the migration. Called in `beforeEach`, since
 * cross-test leakage in idempotency assertions is especially misleading.
 */
export async function truncateAll(pool: Pool): Promise<void> {
  throw new Error('TODO: implement truncateAll');
}

/** Build an app wired to the real repository and a known API key. */
export function buildIntegrationApp(pool: Pool): FastifyInstance {
  throw new Error('TODO: implement buildIntegrationApp');
}

/** Count rows in a table, for asserting that a replay wrote nothing. */
export async function countRows(pool: Pool, table: string): Promise<number> {
  throw new Error('TODO: implement countRows');
}

/** Fetch one event row by id, or null. */
export async function fetchEvent(
  pool: Pool,
  eventId: string,
): Promise<Record<string, unknown> | null> {
  throw new Error('TODO: implement fetchEvent');
}
