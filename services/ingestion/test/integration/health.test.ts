/**
 * Health and readiness endpoints.
 *
 * The split matters operationally: `/healthz` must stay green through a
 * database outage or an orchestrator will restart a healthy process, while
 * `/readyz` must go red so it stops receiving traffic.
 */

import type { FastifyInstance } from 'fastify';
import { Pool } from 'pg';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { AgentEvent, IngestResult } from '../../src/domain/types.js';
import type { EventRepository } from '../../src/domain/ports.js';
import { TEST_DATABASE_URL, buildIntegrationApp, createTestPool } from './setup.js';

// Top-level await so the suite can be skipped at collection time with a clear
// reason, rather than failing every test with a connection error.
let pool: Pool | null = null;
try {
  pool = await createTestPool();
} catch (error) {
  console.warn(
    `skipping ingestion health suite: ${error instanceof Error ? error.message : String(error)}`,
  );
}

afterAll(async () => {
  await pool?.end();
});

const describeDb = pool ? describe : describe.skip;

describeDb('health endpoints against a reachable database', () => {
  let app: FastifyInstance;

  beforeAll(async () => {
    app = await buildIntegrationApp(pool as Pool);
  });

  afterAll(async () => {
    await app.close();
  });

  it('answers GET /healthz with 200 and no authentication', async () => {
    const response = await app.inject({ method: 'GET', url: '/healthz' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toStrictEqual({ status: 'ok' });
  });

  it('answers GET /readyz with 200 ready when the database responds', async () => {
    const response = await app.inject({ method: 'GET', url: '/readyz' });

    expect(response.statusCode).toBe(200);
    expect(response.json()).toStrictEqual({ status: 'ready', database: true });
  });

  it('requires no authentication on /readyz', async () => {
    const response = await app.inject({ method: 'GET', url: '/readyz' });

    // An orchestrator probes without credentials, so a 401 here would take a
    // healthy service out of rotation.
    expect(response.statusCode).not.toBe(401);
  });

  it('answers 404 with a JSON body rather than HTML for an unknown route', async () => {
    const response = await app.inject({ method: 'GET', url: '/this-route-does-not-exist' });

    expect(response.statusCode).toBe(404);
    expect(response.headers['content-type']).toMatch(/application\/json/);
    expect(response.json()).toStrictEqual({ error: 'not_found' });
  });
});

describeDb('health endpoints when the database is unreachable', () => {
  let deadPool: Pool;
  let app: FastifyInstance;

  beforeAll(async () => {
    // Its own pool, closed on purpose: ending the shared one would break the
    // healthy suite above.
    deadPool = new Pool({ connectionString: TEST_DATABASE_URL });
    deadPool.on('error', () => {});
    app = await buildIntegrationApp(deadPool);
    await deadPool.end();
  });

  afterAll(async () => {
    await app.close();
  });

  it('still answers GET /healthz with 200', async () => {
    const response = await app.inject({ method: 'GET', url: '/healthz' });

    // Liveness never touches the database; failing here would restart a
    // process that is working fine.
    expect(response.statusCode).toBe(200);
    expect(response.json()).toStrictEqual({ status: 'ok' });
  });

  it('answers GET /readyz with 503 degraded', async () => {
    const response = await app.inject({ method: 'GET', url: '/readyz' });

    expect(response.statusCode).toBe(503);
    expect(response.json()).toStrictEqual({ status: 'degraded', database: false });
  });
});

/**
 * Repository that reports whatever health the test asks for.
 *
 * A real pool cannot be revived once ended, and recovery is the documented
 * behaviour of `/readyz` ("re-evaluated per request"), so the probe result is
 * the one thing worth faking here. The write methods are unreachable: the
 * health routes never call them.
 */
class TogglableHealthRepository implements EventRepository {
  healthy = true;

  async insertIfAbsent(_event: AgentEvent): Promise<IngestResult> {
    throw new Error('not used by the health routes');
  }

  async insertBatchIfAbsent(_events: AgentEvent[]): Promise<IngestResult[]> {
    throw new Error('not used by the health routes');
  }

  async upsertAgentSeen(_agentId: string, _seenAt: Date): Promise<void> {
    throw new Error('not used by the health routes');
  }

  async healthCheck(): Promise<boolean> {
    return this.healthy;
  }
}

describeDb('readiness re-evaluation', () => {
  const repository = new TogglableHealthRepository();
  let app: FastifyInstance;

  beforeAll(async () => {
    app = await buildIntegrationApp(pool as Pool, { repository });
  });

  afterAll(async () => {
    await app.close();
  });

  it('recovers to 200 once the database returns, without a restart', async () => {
    repository.healthy = false;
    const degraded = await app.inject({ method: 'GET', url: '/readyz' });
    expect(degraded.statusCode).toBe(503);

    repository.healthy = true;
    const recovered = await app.inject({ method: 'GET', url: '/readyz' });

    expect(recovered.statusCode).toBe(200);
    expect(recovered.json()).toStrictEqual({ status: 'ready', database: true });
  });
});
