/**
 * Event submission endpoints.
 */

import type { FastifyPluginAsync } from 'fastify';
import type { ApiKeyStore, Clock, EventRepository } from '../domain/ports.js';
import type { AgentEvent, ValidationIssue } from '../domain/types.js';
import { requireApiKey } from '../plugins/auth.js';
import { parseEnvelope } from '../schemas/event.js';
import { POST_EVENTS_BATCH_SCHEMA, POST_EVENT_SCHEMA } from '../schemas/openapi.js';

export interface EventRoutesOptions {
  repository: EventRepository;
  clock: Clock;
  maxBatchSize: number;
  /** Bound into the per-route `requireApiKey` preHandler below. */
  apiKeyStore: ApiKeyStore;
}

/**
 * Register `POST /v1/events` and `POST /v1/events/batch`.
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
 * `POST /v1/events/batch`
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
  app.post('/v1/events', {
    schema: POST_EVENT_SCHEMA,
    preHandler: [requireApiKey.bind({ apiKeyStore: opts.apiKeyStore })],
  }, async (request, reply) => {
    const client = request.client;
    if (!client) {
      reply.code(401).send({ error: 'unauthorized' });
      return;
    }
    const parsed = parseEnvelope(request.body, client.clientId);
    if (!parsed.ok) {
      reply.code(400).send({ error: 'validation_failed', issues: parsed.error.issues });
      return;
    }

    const result = await opts.repository.insertIfAbsent(parsed.value);
    reply.code(result.status === 'created' ? 201 : 200).send(result);
  });
  app.post('/v1/events/batch', {
    schema: POST_EVENTS_BATCH_SCHEMA,
    preHandler: [requireApiKey.bind({ apiKeyStore: opts.apiKeyStore })],
  }, async (request, reply) => {
    const client = request.client;
    if (!client) {
      reply.code(401).send({ error: 'unauthorized' });
      return;
    }
    const body = request.body as { events?: unknown };
    if (!Array.isArray(body?.events) || body.events.length === 0) {
      reply.code(400).send({
        error: 'validation_failed',
        issues: [{ path: 'events', message: 'Expected a non-empty array' }],
      });
      return;
    }
    if (body.events.length > opts.maxBatchSize) {
      reply.code(400).send({
        error: 'validation_failed',
        issues: [{ path: 'events', message: `Expected at most ${opts.maxBatchSize} events` }],
      });
      return;
    }

    // Per-item, so one bad entry does not cost the caller the whole batch.
    const valid: AgentEvent[] = [];
    const rejected: { index: number; issues: ValidationIssue[] }[] = [];
    body.events.forEach((entry, index) => {
      const parsed = parseEnvelope(entry, client.clientId);
      if (parsed.ok) {
        valid.push(parsed.value);
      } else {
        rejected.push({ index, issues: parsed.error.issues });
      }
    });

    // Results carry `eventId`, not a position: rejected entries shift the
    // indexes, and `rejected[].index` is what maps back to the submitted array.
    const results = await opts.repository.insertBatchIfAbsent(valid);
    reply.code(207).send({
      results,
      accepted: results.filter((r) => r.status === 'created').length,
      duplicates: results.filter((r) => r.status === 'duplicate').length,
      rejected,
    });
  });
};
