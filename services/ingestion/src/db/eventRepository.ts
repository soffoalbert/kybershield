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
import { StorageError, type AgentEvent, type IngestResult } from '../domain/types.js';
import { withTransaction } from './pool.js';

/** Bind parameters for {@link INSERT_EVENT_SQL}, in declaration order. */
function toEventParams(event: AgentEvent): unknown[] {
  return [
    event.eventId,
    event.agentId,
    event.occurredAt,
    event.type,
    event.payload,
    event.raw,
    event.tags,
    event.clientId,
  ];
}

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
    try {
      return await withTransaction(this.pool, async (client) => {
        // Must precede the event: `events.agent_id` is a foreign key into
        // `agents`, so a first-time agent would otherwise fail the insert.
        await client.query(UPSERT_AGENT_SQL, [event.agentId, event.occurredAt]);
        const result = await client.query(INSERT_EVENT_SQL, toEventParams(event));
        // RETURNING yields no rows when ON CONFLICT DO NOTHING skipped the insert.
        return { eventId: event.eventId, status: result.rowCount === 1 ? 'created' : 'duplicate' };
      });
    } catch (error) {
      throw new StorageError('Failed to insert event', error);
    }
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
    if (events.length === 0) {
      return [];
    }

    // ON CONFLICT cannot resolve two conflicting rows inside one statement, so
    // within-batch repeats are collapsed before anything reaches the database.
    const firstOccurrence = new Map<string, AgentEvent>();
    for (const event of events) {
      if (!firstOccurrence.has(event.eventId)) {
        firstOccurrence.set(event.eventId, event);
      }
    }

    try {
      const created = await withTransaction(this.pool, async (client) => {
        const inserted = new Set<string>();
        for (const event of firstOccurrence.values()) {
          // Same foreign key ordering as the single-event path.
          await client.query(UPSERT_AGENT_SQL, [event.agentId, event.occurredAt]);
          const result = await client.query(INSERT_EVENT_SQL, toEventParams(event));
          if (result.rowCount === 1) {
            inserted.add(event.eventId);
          }
        }
        return inserted;
      });

      // One result per input event, in input order. A repeat inside the batch
      // reports `duplicate` even though its first occurrence was created.
      const seen = new Set<string>();
      return events.map((event) => {
        const isRepeat = seen.has(event.eventId);
        seen.add(event.eventId);
        return {
          eventId: event.eventId,
          status: !isRepeat && created.has(event.eventId) ? 'created' : 'duplicate',
        };
      });
    } catch (error) {
      throw new StorageError('Failed to insert events', error);
    }
  }

  /**
   * Record that an agent was seen at `seenAt`, inserting it if unknown.
   *
   * @throws {StorageError} On any driver error.
   */
  async upsertAgentSeen(agentId: string, seenAt: Date): Promise<void> {
    const client = await this.pool.connect();
    try {
      await client.query(UPSERT_AGENT_SQL, [agentId, seenAt]);
    } catch (error) {
      throw new StorageError('Failed to upsert agent seen', error);
    } finally {
      client.release();
    }
  }

  /**
   * Return true if `SELECT 1` succeeds.
   *
   * Never throws; a connection failure resolves to `false`.
   */
  async healthCheck(): Promise<boolean> {
    const client = await this.pool.connect();
    try {
      await client.query('SELECT 1');
      return true;
    } catch (error) {
      return false;
    } finally {
      client.release();
    }
    return false;
  }
}
