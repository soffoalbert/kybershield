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

/** Placeholders `($1, $2, ..., $width)`, `($width+1, ...)`, ... for `rows` rows. */
function valuesPlaceholders(rows: number, width: number): string {
  return Array.from({ length: rows }, (_, row) => {
    const params = Array.from({ length: width }, (_, col) => `$${row * width + col + 1}`);
    return `(${params.join(', ')})`;
  }).join(', ');
}

/**
 * Multi-row form of {@link UPSERT_AGENT_SQL}.
 *
 * Takes explicit first and last seen columns rather than reusing one timestamp
 * for both, because {@link collapseAgents} has already reduced a batch to one
 * row per agent and needs to carry that agent's earliest and latest event.
 */
export function buildUpsertAgentsSql(rowCount: number): string {
  return `
    INSERT INTO agents (agent_id, first_seen_at, last_seen_at)
    VALUES ${valuesPlaceholders(rowCount, 3)}
    ON CONFLICT (agent_id) DO UPDATE
      SET last_seen_at  = GREATEST(agents.last_seen_at, EXCLUDED.last_seen_at),
          first_seen_at = LEAST(agents.first_seen_at, EXCLUDED.first_seen_at)
  `;
}

/** Multi-row form of {@link INSERT_EVENT_SQL}. */
export function buildInsertEventsSql(rowCount: number): string {
  return `
    INSERT INTO events (
      event_id, agent_id, occurred_at, type, payload, raw, tags, client_id
    )
    VALUES ${valuesPlaceholders(rowCount, 8)}
    ON CONFLICT (event_id) DO NOTHING
    RETURNING event_id
  `;
}

/**
 * Reduce a batch to one row per agent, carrying its earliest and latest
 * `occurredAt`.
 *
 * Required, not an optimisation: Postgres rejects an `ON CONFLICT DO UPDATE`
 * whose VALUES list names the same conflict target twice ("cannot affect row a
 * second time"), and a batch from one agent does exactly that.
 */
export function collapseAgents(
  events: AgentEvent[],
): { agentId: string; firstSeen: Date; lastSeen: Date }[] {
  const byAgent = new Map<string, { agentId: string; firstSeen: Date; lastSeen: Date }>();
  for (const event of events) {
    const seen = byAgent.get(event.agentId);
    if (!seen) {
      byAgent.set(event.agentId, {
        agentId: event.agentId,
        firstSeen: event.occurredAt,
        lastSeen: event.occurredAt,
      });
      continue;
    }
    // Min and max rather than last-write-wins: a batch may arrive out of
    // chronological order, and `last_seen_at` must not rewind.
    if (event.occurredAt < seen.firstSeen) seen.firstSeen = event.occurredAt;
    if (event.occurredAt > seen.lastSeen) seen.lastSeen = event.occurredAt;
  }
  return [...byAgent.values()];
}

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

    const unique = [...firstOccurrence.values()];

    try {
      const agents = collapseAgents(unique);

      const created = await withTransaction(this.pool, async (client) => {
        // Two multi-row statements rather than two per event: a 100-event
        // batch used to be 200 sequential round trips, which defeats the point
        // of offering a batch endpoint at all.
        // Agents first, for the same foreign key ordering as the single path.
        await client.query(
          buildUpsertAgentsSql(agents.length),
          agents.flatMap((agent) => [agent.agentId, agent.firstSeen, agent.lastSeen]),
        );
        const result = await client.query(
          buildInsertEventsSql(unique.length),
          unique.flatMap(toEventParams),
        );
        // RETURNING yields only the rows that survived ON CONFLICT.
        return new Set<string>(result.rows.map((row) => row.event_id as string));
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
   * Return true if `SELECT 1` succeeds.
   *
   * Never throws; a connection failure resolves to `false`.
   */
  async healthCheck(): Promise<boolean> {
    let client;
    try {
      // Inside the try: acquiring the client is itself a connection attempt,
      // and it throws on an exhausted or closed pool.
      client = await this.pool.connect();
      await client.query('SELECT 1');
      return true;
    } catch {
      return false;
    } finally {
      client?.release();
    }
  }
}
