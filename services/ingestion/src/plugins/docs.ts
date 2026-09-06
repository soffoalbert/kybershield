/**
 * Interactive API documentation.
 *
 * Registers @fastify/swagger (which builds an OpenAPI 3.1 document from the
 * `schema` attached to each route) and @fastify/swagger-ui (which serves the
 * browsable, try-it-out UI at `/docs`).
 *
 * Must be registered *before* the route plugins: @fastify/swagger collects
 * schemas via an `onRoute` hook, so any route registered earlier is invisible
 * to it.
 */

import type { FastifyInstance } from 'fastify';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import { COMPONENT_SCHEMAS } from '../schemas/openapi.js';

export interface DocsOptions {
  /** Mount point for the UI. The raw document is served at `${routePrefix}/json`. */
  routePrefix?: string;
}

/**
 * Register the OpenAPI document and Swagger UI.
 *
 * Call this before `healthRoutes` and `eventRoutes` in `buildApp`.
 */
export async function registerDocs(
  app: FastifyInstance,
  options: DocsOptions = {},
): Promise<void> {
  const routePrefix = options.routePrefix ?? '/docs';

  // Shared schemas are added to the instance so routes can reference them by
  // `$ref` instead of restating the envelope on every endpoint.
  for (const schema of Object.values(COMPONENT_SCHEMAS)) {
    app.addSchema(schema);
  }

  await app.register(swagger, {
    // Without this, shared schemas are emitted as `def-0`, `def-1`, ... in the
    // components section. Keying on `$id` keeps them readable in the UI and
    // stable for anyone generating a client from the document.
    refResolver: {
      buildLocalReference: (json) => String(json.$id),
    },
    openapi: {
      openapi: '3.1.0',
      info: {
        title: 'KyberShield Ingestion API',
        description:
          'Authenticated, idempotent intake for AI agent activity events.\n\n' +
          '**Authentication.** Every `/v1` endpoint requires `Authorization: Bearer <secret>`, ' +
          'where secrets come from the `API_KEYS` environment variable as `clientId:secret` pairs. ' +
          'Click **Authorize** below to try the endpoints.\n\n' +
          '**Idempotency.** `event_id` is the primary key, so resubmitting an event is safe and ' +
          'returns `200 {"status":"duplicate"}` instead of writing a second row.\n\n' +
          '**Ordering.** Events may arrive out of order. `timestamp` is when the agent says the ' +
          'activity happened; the server separately records arrival time and sequence.',
        version: '0.1.0',
      },
      servers: [{ url: 'http://localhost:3000', description: 'Local Docker Compose' }],
      tags: [
        { name: 'events', description: 'Agent activity submission' },
        { name: 'health', description: 'Liveness and readiness probes' },
      ],
      components: {
        securitySchemes: {
          bearerAuth: {
            type: 'http',
            scheme: 'bearer',
            description: 'A secret from the `API_KEYS` environment variable, e.g. `dev-secret-key`.',
          },
        },
      },
    },
  });

  await app.register(swaggerUi, {
    routePrefix,
    uiConfig: {
      // Endpoints expanded but response schemas collapsed: the useful default
      // for an API this small.
      docExpansion: 'list',
      deepLinking: true,
    },
    // The docs are operator-facing and bound to the Compose network, so the UI
    // itself is unauthenticated even though the endpoints it calls are not.
    staticCSP: true,
  });
}
