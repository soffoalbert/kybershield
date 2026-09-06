/**
 * API key authentication.
 *
 * Deliberately simple for a prototype: a static set of keys supplied through
 * the environment. The trade-offs (long-lived, unrotatable, unscoped keys, no
 * replay protection) are documented in SOLUTION.md; the production answer is
 * HMAC-signed request bodies with a timestamp.
 */

import { createHash, timingSafeEqual } from 'node:crypto';
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
    let match: ClientIdentity | null = null;
    for (const [key, clientId] of this.keys.entries()) {
      // No `break` on a hit, and the result is recorded rather than returned:
      // returning early would make the response time reveal how far down the
      // configured set the matching key sits.
      if (constantTimeEquals(presentedKey, key)) {
        match = { clientId };
      }
    }
    return match;
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
  // SHA-256 first, so both operands are always 32 bytes. Comparing the raw
  // strings would force an early return on a length mismatch, and that return
  // is itself a timing signal that reveals the secret's length. It also lets
  // `timingSafeEqual` be used at all: it throws on differing buffer lengths.
  return timingSafeEqual(sha256(a), sha256(b));
}

function sha256(value: string): Buffer {
  return createHash('sha256').update(value, 'utf8').digest();
}

/**
 * Extract the bearer token from an Authorization header value.
 *
 * Accepts `Bearer <token>` case-insensitively on the scheme, and tolerates
 * surrounding or repeated whitespace, which some HTTP clients introduce.
 * Returns `null` for a missing header, a non-bearer scheme, or an empty token.
 */
export function extractBearerToken(header: string | undefined): string | null {
  if (!header) {
    return null;
  }
  // `\S+` rather than `.+` so a token is never returned with padding, and a
  // header that is nothing but "Bearer" and spaces fails to match.
  const match = /^\s*bearer\s+(\S+)\s*$/i.exec(header);
  return match?.[1] ?? null;
}
