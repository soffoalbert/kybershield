/**
 * In-memory test doubles.
 *
 * Let the unit suite exercise routes, auth, and error mapping with no database
 * and no network. The integration suite uses the real implementations instead.
 */

import type { FastifyInstance } from 'fastify';
import { buildApp } from '../../src/app.js';
import type { AppConfig } from '../../src/config/env.js';
import type { ApiKeyStore, Clock, EventRepository } from '../../src/domain/ports.js';
import type { AgentEvent, ClientIdentity, IngestResult } from '../../src/domain/types.js';

/**
 * EventRepository backed by a Map, with the same duplicate semantics as the
 * Postgres implementation.
 */
export class FakeEventRepository implements EventRepository {
  /** Stored events by id, exposed so tests can assert on what was written. */
  readonly events = new Map<string, AgentEvent>();
  readonly agentsSeen = new Map<string, Date>();
  /** When set, every method rejects with this, to exercise the 503 path. */
  failWith: Error | null = null;
  healthy = true;

  async insertIfAbsent(event: AgentEvent): Promise<IngestResult> {
    if (this.failWith) throw this.failWith;
    if (this.events.has(event.eventId)) {
      return { eventId: event.eventId, status: 'duplicate' };
    }
    this.events.set(event.eventId, event);
    return { eventId: event.eventId, status: 'created' };
  }

  async insertBatchIfAbsent(events: AgentEvent[]): Promise<IngestResult[]> {
    if (this.failWith) throw this.failWith;
    return Promise.all(events.map((event) => this.insertIfAbsent(event)));
  }

  async upsertAgentSeen(agentId: string, seenAt: Date): Promise<void> {
    if (this.failWith) throw this.failWith;
    const currentSeen = this.agentsSeen.get(agentId);
    if (!currentSeen || seenAt > currentSeen) {
      this.agentsSeen.set(agentId, seenAt);
    }
  }

  async healthCheck(): Promise<boolean> {
    if (this.failWith) throw this.failWith;
    return this.healthy;
  }
}

/** ApiKeyStore that accepts a fixed set of keys, without constant-time work. */
export class FakeApiKeyStore implements ApiKeyStore {
  constructor(private readonly keys: Map<string, string> = new Map([['test-key', 'test-client']])) {}

  resolve(presentedKey: string): ClientIdentity | null {
    const client = this.keys.get(presentedKey);
    if (client) {
      return { clientId: client };
    }
    return null;
  }
}

/** Clock pinned to a fixed instant so `received_at` assertions are stable. */
export class FixedClock implements Clock {
  constructor(private current: Date = new Date('2026-08-25T12:00:00Z')) {}

  now(): Date {
    return new Date(this.current);
  }

  /** Move the clock forward, for window-sensitive assertions. */
  advance(ms: number): void {
    this.current = new Date(this.current.getTime() + ms);
  }
}

/**
 * Build a valid event envelope, overriding any field.
 *
 * Keeps tests focused on the one field under test instead of restating a full
 * valid body each time. The shape is the wire format from
 * {@link EventEnvelopeSchema}: snake_case, with an offset-bearing timestamp.
 */
export function buildEnvelope(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    event_id: 'evt-2f9a1c',
    agent_id: 'agent-alpha',
    timestamp: '2026-08-25T12:00:00Z',
    type: 'file_read',
    payload: { path: '/home/alpha/notes.txt' },
    ...overrides,
  };
}

/** Config for an app built entirely from fakes. */
export function buildTestConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    databaseUrl: 'postgres://unused-by-fakes',
    apiKeys: new Map([['test-key', 'test-client']]),
    port: 0,
    host: '127.0.0.1',
    bodyLimitBytes: 512 * 1024,
    requestTimeoutMs: 10_000,
    connectionTimeoutMs: 10_000,
    dbPoolMax: 5,
    dbStatementTimeoutMs: 5_000,
    maxBatchSize: 100,
    // Quiet, so a failing assertion is not buried in request logs.
    logLevel: 'error',
    ...overrides,
  };
}

/**
 * Build an app with fakes wired in, for driving routes through `app.inject()`
 * without a database.
 *
 * Async because `buildApp` awaits its plugin registrations.
 */
export async function buildTestApp(
  overrides: {
    repository?: FakeEventRepository;
    apiKeyStore?: ApiKeyStore;
    clock?: Clock;
    config?: Partial<AppConfig>;
  } = {},
): Promise<{ app: FastifyInstance; repository: FakeEventRepository }> {
  const repository = overrides.repository ?? new FakeEventRepository();
  const config = buildTestConfig(overrides.config);

  const app = await buildApp({
    config,
    repository,
    apiKeyStore: overrides.apiKeyStore ?? new FakeApiKeyStore(config.apiKeys as Map<string, string>),
    clock: overrides.clock ?? new FixedClock(),
  });

  return { app, repository };
}

// --- pg doubles -----------------------------------------------------------
// Enough of `pg`'s Pool and PoolClient to assert on parameter mapping and
// transaction control. Deliberately not a database: the SQL itself is covered
// by the integration suite.

/** One statement executed against {@link FakePgClient}. */
export interface RecordedQuery {
  text: string;
  values: unknown[];
}

/** Decides what a given statement returns, or whether it throws. */
export type QueryResponder = (query: RecordedQuery) => { rowCount: number; rows: unknown[] };

/** A pooled client that records every statement it is handed. */
export class FakePgClient {
  readonly queries: RecordedQuery[] = [];
  /** Arguments each `release()` call received, to assert on broken clients. */
  readonly releases: unknown[] = [];

  constructor(private readonly responder: QueryResponder) {}

  async query(text: string, values: unknown[] = []): Promise<{ rowCount: number; rows: unknown[] }> {
    const recorded = { text, values };
    this.queries.push(recorded);
    return this.responder(recorded);
  }

  release(brokenBy?: unknown): void {
    this.releases.push(brokenBy);
  }

  /** Statement keywords in execution order, e.g. `['BEGIN', 'INSERT', ...]`. */
  get statements(): string[] {
    return this.queries.map((query) => query.text.trim().split(/\s+/)[0]?.toUpperCase() ?? '');
  }

  /** The first recorded statement whose text contains `fragment`. */
  find(fragment: string): RecordedQuery | undefined {
    return this.queries.find((query) => query.text.includes(fragment));
  }
}

/** A pool that hands out one {@link FakePgClient}, or refuses to connect. */
export class FakePgPool {
  readonly client: FakePgClient;
  /** When set, `connect()` rejects with it, as an ended or exhausted pool does. */
  failConnectWith: Error | null = null;
  connectCount = 0;

  constructor(responder: QueryResponder = () => ({ rowCount: 1, rows: [{}] })) {
    this.client = new FakePgClient(responder);
  }

  async connect(): Promise<FakePgClient> {
    this.connectCount += 1;
    if (this.failConnectWith) {
      throw this.failConnectWith;
    }
    return this.client;
  }
}

/**
 * Respond to `INSERT INTO events` as Postgres would for the given event ids,
 * and to everything else as a successful no-op.
 *
 * @param createdEventIds Ids the insert should report as newly written. Any
 *   other id gets `rowCount: 0`, which is how `ON CONFLICT DO NOTHING` reports
 *   a duplicate.
 */
export function eventInsertResponder(createdEventIds: string[]): QueryResponder {
  const created = new Set(createdEventIds);
  return (query) => {
    if (!query.text.includes('INSERT INTO events')) {
      return { rowCount: 1, rows: [{}] };
    }
    const eventId = query.values[0] as string;
    return created.has(eventId)
      ? { rowCount: 1, rows: [{ event_id: eventId }] }
      : { rowCount: 0, rows: [] };
  };
}
