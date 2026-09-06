/**
 * API key resolution and bearer token extraction.
 */

import { describe, expect, it } from 'vitest';
import {
  EnvApiKeyStore,
  constantTimeEquals,
  extractBearerToken,
} from '../../src/auth/apiKeyStore.js';

describe('EnvApiKeyStore.resolve', () => {
  it('resolves a configured secret to its client id', () => {
    const store = new EnvApiKeyStore(new Map([['s3cret', 'demo-agent']]));

    expect(store.resolve('s3cret')).toStrictEqual({ clientId: 'demo-agent' });
  });

  it('returns null for an unknown secret', () => {
    const store = new EnvApiKeyStore(new Map([['s3cret', 'demo-agent']]));

    expect(store.resolve('not-the-secret')).toBeNull();
  });

  it('returns null for an empty string', () => {
    const store = new EnvApiKeyStore(new Map([['s3cret', 'demo-agent']]));

    expect(store.resolve('')).toBeNull();
  });

  it('returns null when no keys are configured', () => {
    const store = new EnvApiKeyStore(new Map());

    // An empty key set must deny everything, never fall open.
    expect(store.resolve('anything')).toBeNull();
    expect(store.resolve('')).toBeNull();
  });

  it('does not match a secret that is a prefix of a configured one', () => {
    const store = new EnvApiKeyStore(new Map([['s3cret', 'demo-agent']]));

    expect(store.resolve('s3c')).toBeNull();
    expect(store.resolve('s3cret-and-more')).toBeNull();
  });

  it('resolves the correct client when several keys are configured', () => {
    const store = new EnvApiKeyStore(
      new Map([
        ['first-secret', 'demo-agent'],
        ['second-secret', 'ci-harness'],
        ['third-secret', 'staging-agent'],
      ]),
    );

    expect(store.resolve('first-secret')).toStrictEqual({ clientId: 'demo-agent' });
    expect(store.resolve('second-secret')).toStrictEqual({ clientId: 'ci-harness' });
    expect(store.resolve('third-secret')).toStrictEqual({ clientId: 'staging-agent' });
  });

  it('treats secrets as case-sensitive', () => {
    const store = new EnvApiKeyStore(new Map([['s3cret', 'demo-agent']]));

    expect(store.resolve('S3CRET')).toBeNull();
  });
});

describe('constantTimeEquals', () => {
  it('returns true for identical strings', () => {
    expect(constantTimeEquals('s3cret', 's3cret')).toBe(true);
  });

  it('returns false for different strings of the same length', () => {
    expect(constantTimeEquals('s3cret', 's3crea')).toBe(false);
  });

  it('returns false for different lengths without throwing', () => {
    expect(constantTimeEquals('s3cret', 's3')).toBe(false);
    expect(constantTimeEquals('s3', 's3cret')).toBe(false);
  });

  it('returns false when either side is empty', () => {
    expect(constantTimeEquals('', 's3cret')).toBe(false);
    expect(constantTimeEquals('s3cret', '')).toBe(false);
  });

  it('returns true for two empty strings', () => {
    expect(constantTimeEquals('', '')).toBe(true);
  });

  it('compares the full input regardless of where the first difference falls', () => {
    // A property check rather than a timing measurement, which would be far
    // too flaky for CI. Both a difference at index 0 and one at the last index
    // must be caught, which rules out an implementation that stops early on a
    // match-so-far.
    expect(constantTimeEquals('Xs3cret', 'as3cret')).toBe(false);
    expect(constantTimeEquals('s3cretX', 's3creta')).toBe(false);
  });
});

describe('extractBearerToken', () => {
  it('extracts the token from "Bearer abc123"', () => {
    expect(extractBearerToken('Bearer abc123')).toBe('abc123');
  });

  it('accepts a lowercase scheme', () => {
    // Some HTTP clients normalise it; the RFC makes the scheme
    // case-insensitive.
    expect(extractBearerToken('bearer abc123')).toBe('abc123');
    expect(extractBearerToken('BEARER abc123')).toBe('abc123');
  });

  it('returns null for undefined', () => {
    expect(extractBearerToken(undefined)).toBeNull();
  });

  it('returns null for an empty header', () => {
    expect(extractBearerToken('')).toBeNull();
  });

  it('returns null for a non-Bearer scheme such as Basic', () => {
    expect(extractBearerToken('Basic YWJjMTIz')).toBeNull();
  });

  it('returns null for "Bearer" with no token', () => {
    expect(extractBearerToken('Bearer')).toBeNull();
    expect(extractBearerToken('Bearer ')).toBeNull();
  });

  it('returns null for a bare token with no scheme', () => {
    expect(extractBearerToken('abc123')).toBeNull();
  });

  it('trims surrounding whitespace from the token', () => {
    expect(extractBearerToken('  Bearer   abc123  ')).toBe('abc123');
  });
});
