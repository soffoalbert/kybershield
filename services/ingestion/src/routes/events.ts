/**
 * Event submission endpoints.
 */

import type { FastifyPluginAsync } from 'fastify';
import type { ApiKeyStore, EventRepository } from '../domain/ports.js';
import type { AgentEvent, ValidationIssue } from '../domain/types.js';
import { authenticatedRoute } from '../plugins/auth.js';
import { replyValidationFailed } from '../replies.js';
import { parseEnvelope } from '../schemas/event.js';
import { POST_EVENTS_BATCH_SCHEMA, POST_EVENT_SCHEMA } from '../schemas/openapi.js';

export interface EventRoutesOptions {
  repository: EventRepository;
  maxBatchSize: number;
  /** Bound into the per-route `requireApiKey` preHandler below. */
  apiKeyStore: ApiKeyStore;
}

/**
 * Register `POST /v1/events` and `POST /v1/events/batch`.
 *
 * Both are wrapped in `authenticatedRoute`, which binds the `preHandler` and
 * passes the resolved client through, so `401` is answered before a handler
 * below ever runs.
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
  // The `body` schemas on these routes are documentation: they give Swagger UI
  // a request shape and a "try it out" template. Letting AJV enforce them too
  // would put two validators with different rules on the same field, and would
  // reject a whole batch over one bad entry, which is the opposite of the
  // per-item `rejected` reporting below. `parseEnvelope` is the sole authority,
  // so validation is compiled away to a no-op here. Scoped to this plugin, so
  // any future route registered elsewhere still validates normally.
  app.setValidatorCompiler(() => (data) => ({ value: data }));

  app.post(
    '/v1/events',
    authenticatedRoute(opts.apiKeyStore, POST_EVENT_SCHEMA, async (request, reply, client) => {
      const parsed = parseEnvelope(request.body, client.clientId);
      if (!parsed.ok) {
        replyValidationFailed(reply, parsed.error.issues);
        return;
      }

      const result = await opts.repository.insertIfAbsent(parsed.value);
      reply.code(result.status === 'created' ? 201 : 200).send(result);
    }),
  );

  app.post(
    '/v1/events/batch',
    authenticatedRoute(
      opts.apiKeyStore,
      POST_EVENTS_BATCH_SCHEMA,
      async (request, reply, client) => {
        const body = request.body as { events?: unknown };
        if (!Array.isArray(body?.events) || body.events.length === 0) {
          replyValidationFailed(reply, [
            { path: 'events', message: 'Expected a non-empty array' },
          ]);
          return;
        }
        if (body.events.length > opts.maxBatchSize) {
          replyValidationFailed(reply, [
            { path: 'events', message: `Expected at most ${opts.maxBatchSize} events` },
          ]);
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
        // indexes, and `rejected[].index` is what maps back to the submitted
        // array.
        const results = await opts.repository.insertBatchIfAbsent(valid);
        reply.code(207).send({
          results,
          accepted: results.filter((r) => r.status === 'created').length,
          duplicates: results.filter((r) => r.status === 'duplicate').length,
          rejected,
        });
      },
    ),
  );
};
