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
    throw new Error('TODO: implement FakeEventRepository.insertIfAbsent');
  }

  async insertBatchIfAbsent(events: AgentEvent[]): Promise<IngestResult[]> {
    throw new Error('TODO: implement FakeEventRepository.insertBatchIfAbsent');
  }

  async upsertAgentSeen(agentId: string, seenAt: Date): Promise<void> {
    throw new Error('TODO: implement FakeEventRepository.upsertAgentSeen');
  }

  async healthCheck(): Promise<boolean> {
    throw new Error('TODO: implement FakeEventRepository.healthCheck');
  }
}

/** ApiKeyStore that accepts a fixed set of keys, without constant-time work. */
export class FakeApiKeyStore implements ApiKeyStore {
  constructor(private readonly keys: Map<string, string> = new Map([['test-key', 'test-client']])) {}

  resolve(presentedKey: string): ClientIdentity | null {
    throw new Error('TODO: implement FakeApiKeyStore.resolve');
  }
}

/** Clock pinned to a fixed instant so `received_at` assertions are stable. */
export class FixedClock implements Clock {
  constructor(private current: Date = new Date('2026-08-25T12:00:00Z')) {}

  now(): Date {
    throw new Error('TODO: implement FixedClock.now');
  }

  /** Move the clock forward, for window-sensitive assertions. */
  advance(ms: number): void {
    throw new Error('TODO: implement FixedClock.advance');
  }
}

/**
 * Build a valid event envelope, overriding any field.
 *
 * Keeps tests focused on the one field under test instead of restating a full
 * valid body each time.
 */
export function buildEnvelope(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  throw new Error('TODO: implement buildEnvelope');
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
  throw new Error('TODO: implement buildTestApp');
}
