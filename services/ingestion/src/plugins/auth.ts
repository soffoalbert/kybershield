/**
 * Fastify authentication hook.
 *
 * Bound as a `preHandler` on each event route rather than registered as a
 * plugin, which keeps auth visible at the endpoint that requires it. Health
 * endpoints stay unauthenticated so an orchestrator can probe them without
 * credentials.
 */

import type {
  FastifyReply,
  FastifyRequest,
  FastifySchema,
  RouteHandlerMethod,
  RouteShorthandOptions,
} from 'fastify';
import type { ApiKeyStore } from '../domain/ports.js';
import type { ClientIdentity } from '../domain/types.js';
import { extractBearerToken } from '../auth/apiKeyStore.js';

declare module 'fastify' {
  interface FastifyRequest {
    /** Set by {@link requireApiKey} once a request is authenticated. */
    client?: ClientIdentity;
  }
}

/**
 * Reject the request unless it carries a valid API key.
 *
 * On success, assigns `request.client` and returns. On failure, replies `401`
 * with a generic body and returns, so the route handler never runs.
 *
 * The response must not distinguish "no header" from "wrong key": both are
 * `401 {"error":"unauthorized"}`, so an attacker learns nothing about which
 * part of their credential was wrong. The distinction is logged, not returned.
 */
export async function requireApiKey(
  this: { apiKeyStore: ApiKeyStore },
  request: FastifyRequest,
  reply: FastifyReply,
): Promise<void> {
  const presentedKey = extractBearerToken(request.headers['authorization'] as string | undefined);
  if (!presentedKey) {
    reply.code(401).send({ error: 'unauthorized' });
    return;
  }
  const client = this.apiKeyStore.resolve(presentedKey);
  if (!client) {
    reply.code(401).send({ error: 'unauthorized' });
    return;
  }
  request.client = client;
}

/**
 * Build route options that authenticate first and hand the caller's identity
 * to the handler.
 *
 * Wiring auth per route means repeating the `preHandler` bind and then, in
 * every handler, re-narrowing the optional `request.client`. That narrowing
 * read as a second 401 path, but {@link requireApiKey} has already replied and
 * halted the chain by then, so it was unreachable. Passing `client` as an
 * argument makes the guarantee structural: a handler written this way cannot
 * be registered without its `preHandler`, and cannot observe a missing client.
 */
export function authenticatedRoute(
  apiKeyStore: ApiKeyStore,
  schema: FastifySchema,
  handler: (
    request: FastifyRequest,
    reply: FastifyReply,
    client: ClientIdentity,
  ) => Promise<void>,
): RouteShorthandOptions & { handler: RouteHandlerMethod } {
  return {
    schema,
    preHandler: [requireApiKey.bind({ apiKeyStore })],
    handler: async function (request, reply) {
      if (!request.client) {
        // Unreachable: the preHandler above either set this or already sent a
        // 401. Thrown rather than answered, because reaching here means the
        // auth chain is broken, which is a bug in this service and not
        // something to report to the caller as a credential problem.
        throw new Error('authenticatedRoute handler ran without an authenticated client');
      }
      await handler(request, reply, request.client);
    },
  };
}
