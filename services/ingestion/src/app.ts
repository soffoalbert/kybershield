/**
 * Fastify application assembly.
 *
 * Split from `server.ts` so tests can build an app with fake dependencies and
 * drive it through `app.inject()` without opening a socket or a database
 * connection.
 */

import fastify, { type FastifyError, type FastifyInstance } from 'fastify';
import { z } from 'zod';
import type { AppConfig } from './config/env.js';
import type { ApiKeyStore, EventRepository } from './domain/ports.js';
import { StorageError } from './domain/types.js';
import { registerDocs } from './plugins/docs.js';
import { eventRoutes } from './routes/events.js';
import { healthRoutes } from './routes/health.js';

export interface AppDependencies {
  config: AppConfig;
  repository: EventRepository;
  apiKeyStore: ApiKeyStore;
}

/**
 * Build a configured, unstarted Fastify instance.
 *
 * Responsibilities:
 * - Instantiate Fastify with the operational limits that keep the service from
 *   hanging: `bodyLimit` from config, plus `requestTimeout` and
 *   `connectionTimeout` so a slow or stalled client is dropped rather than
 *   holding a connection open indefinitely.
 * - Configure the pino logger at `config.logLevel` with a per-request id, and
 *   redact the `authorization` header so credentials never reach the logs.
 * - Register {@link healthRoutes} and {@link eventRoutes}.
 * - Install a `setErrorHandler` that maps:
 *     - zod / validation failures to `400` with the field issues,
 *     - `StorageError` to `503 {error:"storage_unavailable"}`, logging the
 *       underlying cause at error level,
 *     - Fastify's `FST_ERR_CTP_BODY_TOO_LARGE` to `413`,
 *     - malformed JSON to `400 {error:"invalid_json"}`,
 *     - anything else to `500` with a generic body, the real error logged.
 *   No handler may echo the request body back, since payloads routinely carry
 *   secrets.
 * - Install a `setNotFoundHandler` returning a JSON `404`.
 *
 * Async because `registerDocs` awaits its plugin registrations and must run
 * before any route is added.
 *
 * @returns A ready instance. The caller is responsible for `listen()`.
 */
export async function buildApp(deps: AppDependencies): Promise<FastifyInstance> {
  const app = fastify({
    // Operational limits. Together these are what stop a slow or oversized
    // client from occupying a connection indefinitely.
    bodyLimit: deps.config.bodyLimitBytes,
    requestTimeout: deps.config.requestTimeoutMs,
    connectionTimeout: deps.config.connectionTimeoutMs,
    logger: {
      level: deps.config.logLevel,
      // Fastify's default request serialiser omits headers, but redaction is
      // cheap insurance against a future log line that includes them.
      redact: {
        paths: ['req.headers.authorization', 'req.headers.cookie'],
        censor: '[redacted]',
      },
    },
  });

  // Declared up front so Fastify can shape the request object once instead of
  // adding the property ad hoc on every authenticated request. Decorators
  // propagate to child contexts, so the per-route `requireApiKey` hooks in
  // `eventRoutes` assign into a known slot.
  app.decorateRequest('client', undefined);

  // Before the routes: @fastify/swagger collects schemas through an `onRoute`
  // hook and cannot see anything registered earlier.
  await registerDocs(app);

  // Annotated because Fastify infers the handler's error as `unknown`.
  app.setErrorHandler((error: FastifyError, request, reply) => {
    // Body over `bodyLimit`. Fastify raises this before the handler runs.
    if (error.code === 'FST_ERR_CTP_BODY_TOO_LARGE') {
      request.log.warn({ code: error.code }, 'request body too large');
      reply.code(413).send({ error: 'payload_too_large' });
      return;
    }

    // Malformed JSON. Fastify wraps the parse failure in a FastifyError, so
    // this is not an `instanceof SyntaxError` and must be matched by code.
    if (error.code === 'FST_ERR_CTP_INVALID_JSON_BODY') {
      request.log.warn({ code: error.code }, 'malformed JSON body');
      reply.code(400).send({ error: 'invalid_json' });
      return;
    }

    // Fastify's own JSON-schema check. The event routes compile it away so
    // `parseEnvelope` is the only validator there, but a route registered
    // without that opt-out still goes through AJV, so this maps it to the same
    // body shape zod produces and a client sees one contract either way.
    if (error.code === 'FST_ERR_VALIDATION') {
      const issues = (error.validation ?? []).map((entry) => ({
        // AJV reports a missing property against the parent object, so the
        // field name lives in `params` rather than in `instancePath`.
        path:
          (entry.params?.['missingProperty'] as string | undefined) ??
          entry.instancePath.replace(/^\//, '').replaceAll('/', '.'),
        message: entry.message ?? 'invalid',
      }));
      request.log.warn({ issues }, 'request failed schema validation');
      reply.code(400).send({ error: 'validation_failed', issues });
      return;
    }

    if (error instanceof z.ZodError) {
      // Paths and messages only. Zod issues can carry the offending value, and
      // event payloads routinely contain secrets.
      const issues = error.issues.map((issue) => ({
        path: issue.path.join('.'),
        message: issue.message,
      }));
      request.log.warn({ issues }, 'request failed validation');
      reply.code(400).send({ error: 'validation_failed', issues });
      return;
    }

    if (error instanceof StorageError) {
      // The driver error is logged, never returned: it can leak the connection
      // string and the schema.
      request.log.error({ err: error, cause: error.cause }, 'storage error');
      reply.code(503).send({ error: 'storage_unavailable' });
      return;
    }

    request.log.error({ err: error }, 'unhandled error');
    reply.code(500).send({ error: 'internal_server_error' });
  });

  app.setNotFoundHandler((_, reply) => {
    reply.code(404).send({ error: 'not_found' });
  });

  // `eventRoutes` binds `requireApiKey` per route rather than adding a global
  // hook, which keeps auth visible at each endpoint and leaves the health
  // probes unauthenticated.
  await app.register(healthRoutes, { repository: deps.repository });
  await app.register(eventRoutes, {
    repository: deps.repository,
    apiKeyStore: deps.apiKeyStore,
    maxBatchSize: deps.config.maxBatchSize,
  });

  return app;
}
