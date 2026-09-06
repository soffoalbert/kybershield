/**
 * Fastify authentication hook.
 *
 * Bound as a `preHandler` on each event route rather than registered as a
 * plugin, which keeps auth visible at the endpoint that requires it. Health
 * endpoints stay unauthenticated so an orchestrator can probe them without
 * credentials.
 */

import type { FastifyReply, FastifyRequest } from 'fastify';
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
