/**
 * Domain entities for the ingestion service.
 *
 * These mirror the `events` and `agents` tables in db/migrations/001_init.sql.
 * The TypeScript and Python sides define these shapes independently; there is
 * no shared schema registry, which is a documented trade-off.
 */

/**
 * Event type discriminator.
 *
 * The four known types are enumerated for autocomplete and rule authoring, but
 * unknown types are accepted and stored verbatim so a new agent capability
 * does not require an ingestion deploy.
 */
export type EventType =
  | 'http_request'
  | 'file_read'
  | 'shell_command'
  | 'tool_call'
  | (string & {});

/** A validated event ready to be persisted. */
export interface AgentEvent {
  /** Client-supplied identifier. The idempotency key and primary key. */
  eventId: string;
  agentId: string;
  /** When the agent says the activity happened. May arrive out of order. */
  occurredAt: Date;
  type: EventType;
  /** Validated and normalised event details. */
  payload: Record<string, unknown>;
  /** The exact envelope as submitted, stored untouched for forensics. */
  raw: Record<string, unknown>;
  tags: string[];
  /** Which API key submitted this event. Set by the auth layer, not the client. */
  clientId: string;
}

/** Outcome of persisting one event. */
export interface IngestResult {
  eventId: string;
  /** `duplicate` means the event_id already existed and nothing was written. */
  status: 'created' | 'duplicate';
}

/** A caller authenticated by an API key. */
export interface ClientIdentity {
  clientId: string;
}

/** Field-level detail for a rejected request body. */
export interface ValidationIssue {
  /** Dotted path into the request body, e.g. `payload.url`. */
  path: string;
  message: string;
}

/** Discriminated result type used by parsing functions that must not throw. */
export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

/** Aggregated validation failure for one event envelope. */
export interface ValidationError {
  issues: ValidationIssue[];
}

/**
 * Raised when the database rejects or cannot serve a write.
 *
 * Distinguished from validation errors so the error handler can map storage
 * problems to 503 and client mistakes to 400.
 */
export class StorageError extends Error {
  constructor(
    message: string,
    /** The underlying driver error, logged but never returned to the client. */
    override readonly cause?: unknown,
  ) {
    super(message);
    this.name = 'StorageError';
  }
}
