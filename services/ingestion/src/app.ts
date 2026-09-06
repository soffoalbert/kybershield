/**
 * Fastify application assembly.
 *
 * Split from `server.ts` so tests can build an app with fake dependencies and
 * drive it through `app.inject()` without opening a socket or a database
 * connection.
 */

import type { FastifyInstance } from 'fastify';
import type { AppConfig } from './config/env.js';
import type { ApiKeyStore, Clock, EventRepository } from './domain/ports.js';

export interface AppDependencies {
  config: AppConfig;
  repository: EventRepository;
  apiKeyStore: ApiKeyStore;
  /** Defaults to a real system clock when omitted. */
  clock?: Clock;
}

/** Clock backed by `Date.now()`. */
export const systemClock: Clock = {
  now: () => new Date(),
};

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
 * - Register {@link authPlugin}, {@link healthRoutes}, and {@link eventRoutes}.
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
 * @returns A ready instance. The caller is responsible for `listen()`.
 */
export function buildApp(deps: AppDependencies): FastifyInstance {
  throw new Error('TODO: implement buildApp');
}
