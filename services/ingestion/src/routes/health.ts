/**
 * Liveness and readiness endpoints. Unauthenticated by design so an
 * orchestrator can probe them without holding a credential.
 */

import type { FastifyPluginAsync } from 'fastify';
import type { EventRepository } from '../domain/ports.js';
import { HEALTHZ_SCHEMA, READYZ_SCHEMA } from '../schemas/openapi.js';

export interface HealthRoutesOptions {
  repository: EventRepository;
}

/**
 * Register `GET /healthz` and `GET /readyz`.
 *
 * `/healthz` answers `200 {status:"ok"}` as long as the process is running. It
 * must not touch the database: a liveness probe that fails on a transient
 * database outage would restart a perfectly healthy process.
 *
 * `/readyz` probes the database and answers `200 {status:"ready"}` or
 * `503 {status:"degraded", database:false}`.
 */
export const healthRoutes: FastifyPluginAsync<HealthRoutesOptions> = async (app, opts) => {
  app.get('/healthz', { schema: HEALTHZ_SCHEMA }, async (request, reply) => {
    reply.code(200).send({ status: 'ok' });
  });
  app.get('/readyz', { schema: READYZ_SCHEMA }, async (_, reply) => {
    const isReady = await opts.repository.healthCheck();
    reply.code(isReady ? 200 : 503).send({ status: isReady ? 'ready' : 'degraded', database: isReady });
  });  
};
