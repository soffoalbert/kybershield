/**
 * Environment-based configuration.
 *
 * Parsed and validated once at boot so a missing DATABASE_URL or malformed
 * API_KEYS crashes the process immediately rather than failing the first
 * request. Secrets only ever come from the environment, never from files in
 * the repository.
 */

import { z } from 'zod';

/**
 * Raw environment schema.
 *
 * `API_KEYS` is a comma-separated list of `clientId:secret` pairs, e.g.
 * `demo-agent:s3cret,ci-harness:other`. Parsing into a map happens in
 * {@link loadConfig} so the schema stays a faithful description of the env.
 */
export const EnvSchema = z.object({
  DATABASE_URL: z.string().min(1),
  API_KEYS: z.string().min(1),
  PORT: z.coerce.number().int().positive().default(3000),
  HOST: z.string().default('0.0.0.0'),
  BODY_LIMIT_BYTES: z.coerce.number().int().positive().default(512 * 1024),
  REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().default(10_000),
  CONNECTION_TIMEOUT_MS: z.coerce.number().int().positive().default(10_000),
  DB_POOL_MAX: z.coerce.number().int().positive().default(10),
  DB_STATEMENT_TIMEOUT_MS: z.coerce.number().int().positive().default(5_000),
  MAX_BATCH_SIZE: z.coerce.number().int().positive().max(1000).default(100),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace']).default('info'),
});

export type Env = z.infer<typeof EnvSchema>;

/** Validated application configuration. */
export interface AppConfig {
  databaseUrl: string;
  /** Secret to client id. Built from `API_KEYS`. */
  apiKeys: ReadonlyMap<string, string>;
  port: number;
  host: string;
  bodyLimitBytes: number;
  requestTimeoutMs: number;
  connectionTimeoutMs: number;
  dbPoolMax: number;
  dbStatementTimeoutMs: number;
  maxBatchSize: number;
  logLevel: Env['LOG_LEVEL'];
}

/**
 * Parse and validate configuration from the process environment.
 *
 * @param source Environment to read, defaulting to `process.env`. Injectable
 *   so tests do not have to mutate global state.
 * @throws {Error} With a readable summary if any variable is missing or
 *   malformed, or if `API_KEYS` contains an entry that is not `id:secret`,
 *   has a blank secret, or reuses a secret across two client ids.
 */
export function loadConfig(source: NodeJS.ProcessEnv = process.env): AppConfig {
  const env = EnvSchema.parse(source);
  const apiKeys = parseApiKeys(env.API_KEYS);
  return {
    databaseUrl: env.DATABASE_URL,
    apiKeys,
    port: env.PORT,
    host: env.HOST,
    bodyLimitBytes: env.BODY_LIMIT_BYTES,
    requestTimeoutMs: env.REQUEST_TIMEOUT_MS,
    connectionTimeoutMs: env.CONNECTION_TIMEOUT_MS,
    dbPoolMax: env.DB_POOL_MAX,
    dbStatementTimeoutMs: env.DB_STATEMENT_TIMEOUT_MS,
    maxBatchSize: env.MAX_BATCH_SIZE,
    logLevel: env.LOG_LEVEL,
  };  
}

/**
 * Parse the `API_KEYS` value into a secret to client id map.
 *
 * Keyed by secret because lookup happens by presented secret. Exported
 * separately so it can be unit tested without a full environment.
 *
 * @throws {Error} On a malformed entry, a blank secret, or a duplicate secret.
 */
export function parseApiKeys(raw: string): Map<string, string> {
  const map = new Map<string, string>();
  raw.split(',').forEach((entry, index) => {
    const trimmed = entry.trim();
    // Position rather than content in every message below: this text reaches
    // stderr on a failed boot, and the entry contains a secret.
    const position = `API_KEYS entry ${index + 1}`;

    // Split on the first colon only, so a base64 or URL-shaped secret that
    // contains colons survives intact instead of being silently truncated.
    const separator = trimmed.indexOf(':');
    if (separator === -1) {
      throw new Error(`${position} is not in "clientId:secret" form`);
    }

    const clientId = trimmed.slice(0, separator).trim();
    const secret = trimmed.slice(separator + 1).trim();
    if (!clientId) {
      throw new Error(`${position} has a blank client id`);
    }
    if (!secret) {
      throw new Error(`${position} has a blank secret`);
    }

    // A reused secret makes the map ambiguous: the last entry parsed would win
    // and every event from the other client would be misattributed.
    const existing = map.get(secret);
    if (existing) {
      throw new Error(
        `${position} reuses a secret already assigned to client "${existing}"`,
      );
    }

    map.set(secret, clientId);
  });
  return map;
}
