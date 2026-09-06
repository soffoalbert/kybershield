/**
 * Event submission endpoints.
 */

import type { FastifyPluginAsync } from 'fastify';
import type { ApiKeyStore, Clock, EventRepository } from '../domain/ports.js';
import type { AgentEvent } from '../domain/types.js';
import { requireApiKey } from '../plugins/auth.js';

export interface EventRoutesOptions {
  repository: EventRepository;
  clock: Clock;
  maxBatchSize: number;
  /** Bound into the per-route `requireApiKey` preHandler below. */
  apiKeyStore: ApiKeyStore;
}

/**
 * Register `POST /v1/events` and `POST /v1/events:batch`.
 *
 * Both require authentication; the caller registers {@link authPlugin} in the
 * same scope.
 *
 * `POST /v1/events`
 * - `201 {eventId, status:"created"}` when the event was stored.
 * - `200 {eventId, status:"duplicate"}` when `event_id` already existed.
 *   200 rather than 409 because a replay is a success from the agent's point
 *   of view: the event is durably recorded and retrying is the correct
 *   behaviour for an at-least-once client.
 * - `400 {error:"validation_failed", issues:[{path, message}]}`.
 * - `401 {error:"unauthorized"}`.
 * - `413` when the body exceeds `BODY_LIMIT_BYTES` (raised by Fastify).
 * - `503 {error:"storage_unavailable"}` on a StorageError.
 *
 * `POST /v1/events:batch`
 * - Body `{events: [...]}`, at most `maxBatchSize` entries.
 * - `207 {results:[{eventId, status}], accepted, duplicates, rejected:[{index, issues}]}`.
 *   Multi-status because a batch can legitimately mix outcomes; a single code
 *   would force the client to guess which events landed.
 * - Validation is per-item: invalid entries are reported by index and the
 *   valid remainder is still stored.
 * - `400` only if the envelope itself is unusable (not an object, empty
 *   `events`, or over the size limit).
 */
export const eventRoutes: FastifyPluginAsync<EventRoutesOptions> = async (app, opts) => {
  app.post('/v1/events', { preHandler: [requireApiKey.bind({ apiKeyStore: opts.apiKeyStore })] }, async (request, reply) => {
    const client = request.client;
    if (!client) {
      reply.code(401).send({ error: 'unauthorized' });
      return;
    }
    const event = request.body as AgentEvent;
    const result = await opts.repository.insertIfAbsent(event);
    reply.code(result.status === 'created' ? 201 : 200).send({ eventId: result.eventId, status: result.status });
  });
  app.post('/v1/events:batch', { preHandler: [requireApiKey.bind({ apiKeyStore: opts.apiKeyStore })] }, async (request, reply) => {
    const client = request.client;
    if (!client) {
      reply.code(401).send({ error: 'unauthorized' });
      return;
    }
    const events = request.body as AgentEvent[];
    const results = await opts.repository.insertBatchIfAbsent(events);
    reply.code(207).send({ results: results.map(result => ({ eventId: result.eventId, status: result.status })) });
  });
};
