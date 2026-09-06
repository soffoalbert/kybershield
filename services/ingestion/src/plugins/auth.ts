/**
 * Fastify authentication hook.
 *
 * Registered as a `preHandler` on the event routes only. Health endpoints stay
 * unauthenticated so an orchestrator can probe them without credentials.
 */

import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from 'fastify';
import type { ApiKeyStore } from '../domain/ports.js';
import type { ClientIdentity } from '../domain/types.js';
import { extractBearerToken } from '../auth/apiKeyStore.js';

declare module 'fastify' {
  interface FastifyRequest {
    /** Set by {@link requireApiKey} once a request is authenticated. */
    client?: ClientIdentity;
  }
}

export interface AuthPluginOptions {
  apiKeyStore: ApiKeyStore;
}

/**
 * Decorate the instance with `requireApiKey` and the request with `client`.
 *
 * Registered with `fastify-plugin` semantics disabled intentionally: the
 * decorator is scoped to the routes that register this plugin.
 */
export const authPlugin: FastifyPluginAsync<AuthPluginOptions> = async (app, opts) => {
  app.decorateRequest('client', undefined);
  app.addHook('preHandler', requireApiKey.bind({ apiKeyStore: opts.apiKeyStore }));
};

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
