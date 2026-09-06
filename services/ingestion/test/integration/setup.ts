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

import { readFile, readdir } from 'node:fs/promises';
import { Pool } from 'pg';
import type { FastifyInstance } from 'fastify';
import { buildApp, systemClock } from '../../src/app.js';
import { EnvApiKeyStore } from '../../src/auth/apiKeyStore.js';
import type { AppConfig } from '../../src/config/env.js';
import { PgEventRepository } from '../../src/db/eventRepository.js';
import type { Clock, EventRepository } from '../../src/domain/ports.js';

/**
 * Connection string for the test database.
 *
 * A database of its own, not the compose `kybershield` one: `truncateAll`
 * would otherwise wipe whatever the developer was looking at, and the running
 * analyser would be polling the same tables a test is asserting on.
 */
export const TEST_DATABASE_URL =
  process.env.TEST_DATABASE_URL ??
  'postgres://kybershield:kybershield@localhost:5432/kybershield_test';

/** Server-level connection used to create the test database if it is absent. */
const MAINTENANCE_DATABASE_URL =
  process.env.MAINTENANCE_DATABASE_URL ??
  'postgres://kybershield:kybershield@localhost:5432/postgres';

const MIGRATIONS_DIR = new URL('../../../../db/migrations/', import.meta.url);

/** The one key {@link buildIntegrationApp} accepts, and the client it maps to. */
export const TEST_API_KEY = 'test-api-key-123';
export const TEST_CLIENT_ID = 'test-client';

/** Tables truncated between tests, ordered so the foreign keys stay satisfied. */
const MANAGED_TABLES = ['alerts', 'events', 'agents'] as const;

/**
 * Open a pool against the test database.
 *
 * Verifies the connection eagerly and rejects with an actionable message if
 * nothing is listening, so a developer without Docker running sees "start
 * Postgres" instead of a wall of connection errors. The caller turns that into
 * a skipped suite.
 */
export async function createTestPool(): Promise<Pool> {
  await createDatabaseIfAbsent();

  const pool = new Pool({ connectionString: TEST_DATABASE_URL, max: 5 });
  // `pg` re-emits idle client errors on the pool, and an unhandled 'error'
  // event would take the test process down.
  pool.on('error', () => {});

  try {
    const client = await pool.connect();
    try {
      await client.query('SELECT 1');
      await applyMigrationsIfAbsent(client);
    } finally {
      client.release();
    }
  } catch (error) {
    await pool.end().catch(() => {});
    throw new Error(
      `PostgreSQL is not reachable at ${TEST_DATABASE_URL}. ` +
        'Start it with `docker compose up -d postgres`. ' +
        `(${error instanceof Error ? error.message : String(error)})`,
    );
  }

  return pool;
}

/**
 * Create the test database unless it already exists.
 *
 * So a fresh checkout needs only `docker compose up -d postgres` before
 * `npm test`. CREATE DATABASE cannot run inside a transaction or take a bind
 * parameter, hence the interpolated literal name.
 */
async function createDatabaseIfAbsent(): Promise<void> {
  const name = new URL(TEST_DATABASE_URL).pathname.replace(/^\//, '');
  const maintenance = new Pool({ connectionString: MAINTENANCE_DATABASE_URL, max: 1 });
  maintenance.on('error', () => {});
  try {
    const existing = await maintenance.query('SELECT 1 FROM pg_database WHERE datname = $1', [
      name,
    ]);
    if (existing.rowCount === 0) {
      await maintenance.query(`CREATE DATABASE "${name.replaceAll('"', '""')}"`);
    }
  } catch {
    // Left to the caller's own connection attempt, which reports the
    // actionable "start Postgres" message.
  } finally {
    await maintenance.end().catch(() => {});
  }
}

/**
 * Apply the migrations once, if the schema is not there yet.
 *
 * Presence of `events` stands in for a version table: the migrations are
 * additive and this database exists only for the suite.
 */
async function applyMigrationsIfAbsent(client: {
  query: (text: string) => Promise<{ rows: unknown[] }>;
}): Promise<void> {
  const probe = await client.query("SELECT to_regclass('public.events') AS present");
  if ((probe.rows[0] as { present: string | null }).present) {
    return;
  }
  const files = (await readdir(MIGRATIONS_DIR)).filter((name) => name.endsWith('.sql')).sort();
  for (const file of files) {
    await client.query(await readFile(new URL(file, MIGRATIONS_DIR), 'utf8'));
  }
}

/**
 * Delete all rows and reset the analysis cursor.
 *
 * Truncate with CASCADE rather than dropping the schema, so each test starts
 * clean without paying to re-run the migration. Called in `beforeEach`, since
 * cross-test leakage in idempotency assertions is especially misleading.
 *
 * `RESTART IDENTITY` resets the `ingest_seq` sequence, which keeps the
 * arrival-order assertions readable.
 */
export async function truncateAll(pool: Pool): Promise<void> {
  await pool.query(
    `TRUNCATE TABLE ${MANAGED_TABLES.join(', ')} RESTART IDENTITY CASCADE`,
  );
  await pool.query('UPDATE analysis_cursor SET last_ingest_seq = 0 WHERE id = 1');
}

/** Overrides for the limits a test needs to push against. */
export interface IntegrationAppOptions {
  bodyLimitBytes?: number;
  maxBatchSize?: number;
  clock?: Clock;
  /**
   * Replaces the Postgres repository. Only for behaviour that a real database
   * cannot exhibit on demand, such as recovering from an outage mid-suite.
   */
  repository?: EventRepository;
}

/**
 * Build an app wired to the real repository and a known API key.
 *
 * Config is constructed rather than read from the environment: `loadConfig`
 * would couple every test run to whatever `DATABASE_URL` and `API_KEYS` happen
 * to be exported, and the limits below need to be overridable per test.
 *
 * Async because `buildApp` awaits its plugin registrations.
 */
export async function buildIntegrationApp(
  pool: Pool,
  options: IntegrationAppOptions = {},
): Promise<FastifyInstance> {
  const config: AppConfig = {
    databaseUrl: TEST_DATABASE_URL,
    apiKeys: new Map([[TEST_API_KEY, TEST_CLIENT_ID]]),
    port: 0,
    host: '127.0.0.1',
    bodyLimitBytes: options.bodyLimitBytes ?? 512 * 1024,
    requestTimeoutMs: 10_000,
    connectionTimeoutMs: 10_000,
    dbPoolMax: 5,
    dbStatementTimeoutMs: 5_000,
    maxBatchSize: options.maxBatchSize ?? 100,
    // Quiet, so a failing assertion is not buried in request logs.
    logLevel: 'error',
  };

  return buildApp({
    config,
    repository: options.repository ?? new PgEventRepository(pool),
    apiKeyStore: new EnvApiKeyStore(config.apiKeys),
    clock: options.clock ?? systemClock,
  });
}

/** Count rows in a table, for asserting that a replay wrote nothing. */
export async function countRows(pool: Pool, table: string): Promise<number> {
  if (!MANAGED_TABLES.includes(table as (typeof MANAGED_TABLES)[number])) {
    throw new Error(`Refusing to count unknown table: ${table}`);
  }
  // Interpolated because a table name cannot be a bind parameter; the
  // whitelist above is what makes that safe.
  const result = await pool.query<{ count: string }>(`SELECT count(*) AS count FROM ${table}`);
  return Number(result.rows[0]?.count ?? 0);
}

/** Fetch one event row by id, or null. */
export async function fetchEvent(
  pool: Pool,
  eventId: string,
): Promise<Record<string, unknown> | null> {
  const result = await pool.query<Record<string, unknown>>(
    'SELECT * FROM events WHERE event_id = $1',
    [eventId],
  );
  return result.rows[0] ?? null;
}

/** Fetch one agent row by id, or null. */
export async function fetchAgent(
  pool: Pool,
  agentId: string,
): Promise<Record<string, unknown> | null> {
  const result = await pool.query<Record<string, unknown>>(
    'SELECT * FROM agents WHERE agent_id = $1',
    [agentId],
  );
  return result.rows[0] ?? null;
}
