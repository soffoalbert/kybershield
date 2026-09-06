/**
 * In-memory test doubles.
 *
 * Let the unit suite exercise routes, auth, and error mapping with no database
 * and no network. The integration suite uses the real implementations instead.
 */

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
    return Promise.all(events.map(ev => this.insertIfAbsent(ev)));
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
 * valid body each time.
 */
export function buildEnvelope(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'evt_123',
    agent_id: 'agent_abc',
    received_at: '2026-08-25T12:00:00Z',
    type: 'test.type',
    body: { foo: 'bar' },
    ...overrides,
  };
}

/** Build a test app with fakes wired in. */
export function buildTestApp(overrides?: {
  repository?: EventRepository;
  apiKeyStore?: ApiKeyStore;
  clock?: Clock;
  bodyLimitBytes?: number;
}): {
  app: import('fastify').FastifyInstance;
  repository: FakeEventRepository;
} {
  // Require real application only at runtime in tests to avoid breaking build
  const Fastify = require('fastify');
  const { buildApp } = require('../../src/app.js');

  const repository = (overrides?.repository as FakeEventRepository) || new FakeEventRepository();
  const apiKeyStore = overrides?.apiKeyStore || new FakeApiKeyStore();
  const clock = overrides?.clock || new FixedClock();
  const bodyLimitBytes = overrides?.bodyLimitBytes || 1024 * 1024;

  const app = buildApp({
    repository,
    apiKeyStore,
    clock,
    bodyLimitBytes,
    fastifyFactory: () => Fastify(),
  });

  return { app, repository };
}
