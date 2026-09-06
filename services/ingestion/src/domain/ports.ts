/**
 * Ports (interfaces) the ingestion service depends on.
 *
 * Routes are written against these rather than concrete Postgres classes so
 * unit tests can pass in-memory fakes without a database.
 */

import type { AgentEvent, ClientIdentity, IngestResult } from './types.js';

export interface EventRepository {
  /**
   * Persist one event, ignoring it if `event_id` already exists.
   *
   * Implemented as `INSERT ... ON CONFLICT (event_id) DO NOTHING`, so
   * concurrent duplicate submissions are safe without application locking.
   *
   * @returns `created` if a row was written, `duplicate` if one already existed.
   * @throws {StorageError} If the database is unreachable or rejects the write.
   */
  insertIfAbsent(event: AgentEvent): Promise<IngestResult>;

  /**
   * Persist many events in one transaction, ignoring duplicates.
   *
   * @returns One result per input event, in the same order.
   * @throws {StorageError} If the transaction fails; nothing is persisted.
   */
  insertBatchIfAbsent(events: AgentEvent[]): Promise<IngestResult[]>;

  /**
   * Record that an agent was seen, inserting it if unknown.
   *
   * `last_seen_at` only moves forward, so an out-of-order event carrying an
   * older timestamp must not rewind it.
   */
  upsertAgentSeen(agentId: string, seenAt: Date): Promise<void>;

  /**
   * Return true if the database answers a trivial query.
   *
   * Must never throw; connection failures are reported as `false` so the
   * readiness endpoint can answer 503 instead of 500.
   */
  healthCheck(): Promise<boolean>;
}

export interface ApiKeyStore {
  /**
   * Resolve a presented secret to the client it belongs to.
   *
   * Must compare in constant time with respect to the secret's contents so a
   * caller cannot recover a key byte by byte from response timing.
   *
   * @returns The matching client, or `null` if the key is unknown or empty.
   */
  resolve(presentedKey: string): ClientIdentity | null;
}

/** Injectable clock so tests can pin `received_at` and `last_seen_at`. */
export interface Clock {
  now(): Date;
}
