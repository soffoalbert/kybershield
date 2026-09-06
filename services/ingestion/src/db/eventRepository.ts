/**
 * PostgreSQL-backed event storage.
 *
 * Idempotency lives in the schema rather than here: `events.event_id` is the
 * primary key, so `ON CONFLICT DO NOTHING` makes concurrent duplicate
 * submissions safe without any application-level locking or read-then-write
 * race.
 */

import type { Pool } from 'pg';
import type { EventRepository } from '../domain/ports.js';
import type { AgentEvent, IngestResult } from '../domain/types.js';

/**
 * Insert an event, doing nothing if `event_id` already exists.
 *
 * `RETURNING event_id` yields zero rows on conflict, which is how a duplicate
 * is detected without a separate SELECT.
 */
export const INSERT_EVENT_SQL = `
  INSERT INTO events (
    event_id, agent_id, occurred_at, type, payload, raw, tags, client_id
  )
  VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
  ON CONFLICT (event_id) DO NOTHING
  RETURNING event_id
`;

/**
 * Insert or refresh an agent.
 *
 * `GREATEST` on `last_seen_at` keeps the column monotonic, so an out-of-order
 * event carrying an older timestamp cannot rewind it. `LEAST` does the mirror
 * for `first_seen_at`, so a late event that predates everything seen so far
 * correctly moves the agent's start backwards.
 */
export const UPSERT_AGENT_SQL = `
  INSERT INTO agents (agent_id, first_seen_at, last_seen_at)
  VALUES ($1, $2, $2)
  ON CONFLICT (agent_id) DO UPDATE
    SET last_seen_at  = GREATEST(agents.last_seen_at, EXCLUDED.last_seen_at),
        first_seen_at = LEAST(agents.first_seen_at, EXCLUDED.first_seen_at)
`;

export class PgEventRepository implements EventRepository {
  constructor(private readonly pool: Pool) {}

  /**
   * Upsert the agent and insert the event in one transaction.
   *
   * Both statements must be atomic: the `events.agent_id` foreign key means a
   * committed event without its agent row is impossible, and a committed agent
   * row for a rolled-back event would be misleading noise.
   *
   * @returns `created` if a row was written, `duplicate` if the insert
   *   conflicted on `event_id`.
   * @throws {StorageError} Wrapping any driver error, with the original
   *   attached as `cause` for logging.
   */
  async insertIfAbsent(event: AgentEvent): Promise<IngestResult> {
    throw new Error('TODO: implement PgEventRepository.insertIfAbsent');
  }

  /**
   * Insert many events in a single transaction.
   *
   * Deduplicates by `eventId` within the input before touching the database,
   * since `ON CONFLICT` cannot resolve two conflicting rows in one statement.
   * A repeat inside the same batch is reported as `duplicate`.
   *
   * @returns One result per input event, in input order, including entries for
   *   the within-batch duplicates that were collapsed.
   * @throws {StorageError} If the transaction fails; nothing is persisted.
   */
  async insertBatchIfAbsent(events: AgentEvent[]): Promise<IngestResult[]> {
    throw new Error('TODO: implement PgEventRepository.insertBatchIfAbsent');
  }

  /**
   * Record that an agent was seen at `seenAt`, inserting it if unknown.
   *
   * @throws {StorageError} On any driver error.
   */
  async upsertAgentSeen(agentId: string, seenAt: Date): Promise<void> {
    throw new Error('TODO: implement PgEventRepository.upsertAgentSeen');
  }

  /**
   * Return true if `SELECT 1` succeeds.
   *
   * Never throws; a connection failure resolves to `false`.
   */
  async healthCheck(): Promise<boolean> {
    throw new Error('TODO: implement PgEventRepository.healthCheck');
  }
}
