/**
 * API key authentication.
 *
 * Deliberately simple for a prototype: a static set of keys supplied through
 * the environment. The trade-offs (long-lived, unrotatable, unscoped keys, no
 * replay protection) are documented in SOLUTION.md; the production answer is
 * HMAC-signed request bodies with a timestamp.
 */

import type { ApiKeyStore } from '../domain/ports.js';
import type { ClientIdentity } from '../domain/types.js';

/**
 * Resolves keys from an in-memory map built from the `API_KEYS` env variable.
 */
export class EnvApiKeyStore implements ApiKeyStore {
  /**
   * @param keys Secret to client id, as produced by `parseApiKeys`.
   */
  constructor(private readonly keys: ReadonlyMap<string, string>) {}

  /**
   * Resolve a presented secret to its client.
   *
   * Compares against every configured key using a constant-time comparison and
   * does not short-circuit on the first match, so neither the secret's content
   * nor its position in the configured set is observable through timing.
   *
   * @returns The matching client, or `null` for an unknown or empty key.
   */
  resolve(presentedKey: string): ClientIdentity | null {
    throw new Error('TODO: implement EnvApiKeyStore.resolve');
  }
}

/**
 * Compare two strings without leaking their contents through timing.
 *
 * Hashes both inputs to a fixed length before comparing, so `timingSafeEqual`
 * never sees mismatched buffer lengths and the comparison cost is independent
 * of how much of the secret the caller guessed correctly.
 *
 * Note that overall length is still coarsely observable via the hashing step;
 * that is acceptable, since key length is not the secret.
 */
export function constantTimeEquals(a: string, b: string): boolean {
  throw new Error('TODO: implement constantTimeEquals');
}

/**
 * Extract the bearer token from an Authorization header value.
 *
 * Accepts `Bearer <token>` case-insensitively on the scheme. Returns `null`
 * for a missing header, a non-bearer scheme, or an empty token.
 */
export function extractBearerToken(header: string | undefined): string | null {
  throw new Error('TODO: implement extractBearerToken');
}
