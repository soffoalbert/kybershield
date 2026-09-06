/**
 * Configuration parsing.
 *
 * Boot-time validation, so every failure here is one the operator sees
 * immediately rather than on the first request.
 */

import { describe, expect, it } from 'vitest';
import { loadConfig, parseApiKeys } from '../../src/config/env.js';

/** The minimum environment `loadConfig` accepts. */
function baseEnv(overrides: Record<string, string | undefined> = {}) {
  return {
    DATABASE_URL: 'postgres://kybershield:kybershield@localhost:5432/kybershield',
    API_KEYS: 'demo-agent:s3cret',
    ...overrides,
  };
}

describe('parseApiKeys', () => {
  it('parses a single id:secret pair into a secret-keyed map', () => {
    // Keyed by secret because lookup happens by presented secret.
    expect(parseApiKeys('demo-agent:s3cret')).toStrictEqual(new Map([['s3cret', 'demo-agent']]));
  });

  it('parses several comma-separated pairs', () => {
    expect(parseApiKeys('demo-agent:s3cret,ci-harness:other')).toStrictEqual(
      new Map([
        ['s3cret', 'demo-agent'],
        ['other', 'ci-harness'],
      ]),
    );
  });

  it('trims whitespace around ids and secrets', () => {
    expect(parseApiKeys(' demo-agent : s3cret , ci-harness : other ')).toStrictEqual(
      new Map([
        ['s3cret', 'demo-agent'],
        ['other', 'ci-harness'],
      ]),
    );
  });

  it('throws on an entry with no colon', () => {
    expect(() => parseApiKeys('demo-agent')).toThrow(/not in "clientId:secret" form/);
  });

  it('throws on a blank secret such as "client:"', () => {
    expect(() => parseApiKeys('demo-agent:')).toThrow(/blank secret/);
  });

  it('throws on a blank client id such as ":secret"', () => {
    expect(() => parseApiKeys(':s3cret')).toThrow(/blank client id/);
  });

  it('throws when two clients share a secret', () => {
    // A shared secret makes the map ambiguous and silently misattributes
    // events to whichever entry parsed last.
    expect(() => parseApiKeys('demo-agent:same,ci-harness:same')).toThrow(/reuses a secret/);
  });

  it('accepts a secret containing a colon', () => {
    // Split on the first colon only, so base64 or URL-shaped secrets survive.
    expect(parseApiKeys('demo-agent:aGVsbG8=:v2')).toStrictEqual(
      new Map([['aGVsbG8=:v2', 'demo-agent']]),
    );
  });

  it('never includes the secret in an error message', () => {
    // This text reaches stderr on a failed boot.
    expect(() => parseApiKeys('demo-agent:same,ci-harness:same')).toThrow(
      expect.not.stringContaining('same'),
    );
  });
});

describe('loadConfig', () => {
  it('returns a config when every required variable is present', () => {
    const config = loadConfig(baseEnv());

    expect(config.databaseUrl).toBe(
      'postgres://kybershield:kybershield@localhost:5432/kybershield',
    );
    expect(config.apiKeys).toStrictEqual(new Map([['s3cret', 'demo-agent']]));
  });

  it('throws when DATABASE_URL is absent', () => {
    expect(() => loadConfig(baseEnv({ DATABASE_URL: undefined }))).toThrow();
  });

  it('throws when API_KEYS is absent', () => {
    expect(() => loadConfig(baseEnv({ API_KEYS: undefined }))).toThrow();
  });

  it('applies defaults for optional variables', () => {
    const config = loadConfig(baseEnv());

    expect(config.port).toBe(3000);
    expect(config.host).toBe('0.0.0.0');
    expect(config.bodyLimitBytes).toBe(512 * 1024);
    expect(config.requestTimeoutMs).toBe(10_000);
    expect(config.connectionTimeoutMs).toBe(10_000);
    expect(config.dbPoolMax).toBe(10);
    expect(config.dbStatementTimeoutMs).toBe(5_000);
    expect(config.maxBatchSize).toBe(100);
    expect(config.logLevel).toBe('info');
  });

  it('coerces numeric strings to numbers', () => {
    const config = loadConfig(baseEnv({ PORT: '8080', BODY_LIMIT_BYTES: '2048' }));

    expect(config.port).toBe(8080);
    expect(config.bodyLimitBytes).toBe(2048);
  });

  it('throws on a non-numeric PORT', () => {
    expect(() => loadConfig(baseEnv({ PORT: 'not-a-port' }))).toThrow();
  });

  it('throws on a negative PORT', () => {
    expect(() => loadConfig(baseEnv({ PORT: '-1' }))).toThrow();
  });

  it('throws on an unrecognised LOG_LEVEL', () => {
    expect(() => loadConfig(baseEnv({ LOG_LEVEL: 'chatty' }))).toThrow();
  });

  it('reads from the injected source rather than process.env', () => {
    // Keeps the suite free of global environment mutation.
    const before = process.env['PORT'];
    process.env['PORT'] = '9999';
    try {
      expect(loadConfig(baseEnv({ PORT: '4321' })).port).toBe(4321);
    } finally {
      if (before === undefined) {
        delete process.env['PORT'];
      } else {
        process.env['PORT'] = before;
      }
    }
  });
});
