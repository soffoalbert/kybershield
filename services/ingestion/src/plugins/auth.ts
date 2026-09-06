/**
 * Fastify authentication hook.
 *
 * Registered as a `preHandler` on the event routes only. Health endpoints stay
 * unauthenticated so an orchestrator can probe them without credentials.
 */

import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from 'fastify';
import type { ApiKeyStore } from '../domain/ports.js';
import type { ClientIdentity } from '../domain/types.js';

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
  throw new Error('TODO: implement authPlugin');
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
  throw new Error('TODO: implement requireApiKey');
}
