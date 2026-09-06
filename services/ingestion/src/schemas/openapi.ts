/**
 * JSON Schema definitions for the OpenAPI document.
 *
 * Kept separate from the zod schemas in `event.ts` on purpose. Those validate
 * untrusted input and are the security boundary; these describe the contract
 * to a reader and drive Swagger UI. Fastify's `schema.response` also serialises
 * responses against these, so a handler cannot accidentally leak a field that
 * is not documented here.
 *
 * Request bodies are documented but deliberately *not* validated by Fastify:
 * `parseEnvelope` owns validation so that the batch endpoint can report
 * per-item failures by index, which a whole-body schema rejection cannot do.
 */

/** Shared component schemas, registered once and referenced by `$ref`. */
export const COMPONENT_SCHEMAS = {
  EventEnvelope: {
    $id: 'EventEnvelope',
    type: 'object',
    required: ['event_id', 'agent_id', 'timestamp', 'type', 'payload'],
    properties: {
      event_id: {
        type: 'string',
        description: 'Client-supplied identifier. Resubmitting the same value is a no-op.',
        examples: ['evt-2f9a1c'],
      },
      agent_id: { type: 'string', examples: ['agent-alpha'] },
      timestamp: {
        type: 'string',
        format: 'date-time',
        description:
          'ISO-8601 with an explicit offset. May be older than an already-submitted event; out-of-order arrival is supported.',
        examples: ['2026-08-25T10:00:00Z'],
      },
      type: {
        type: 'string',
        description:
          'Event type. The four known values are validated against a payload schema; unknown types are accepted and stored verbatim.',
        examples: ['file_read', 'http_request', 'shell_command', 'tool_call'],
      },
      payload: {
        type: 'object',
        additionalProperties: true,
        description: 'Event details. Shape depends on `type`.',
        examples: [{ path: '/home/app/.aws/credentials' }],
      },
      tags: {
        type: 'array',
        items: { type: 'string' },
        maxItems: 50,
      },
    },
  },

  IngestResult: {
    $id: 'IngestResult',
    type: 'object',
    required: ['eventId', 'status'],
    properties: {
      eventId: { type: 'string' },
      status: {
        type: 'string',
        enum: ['created', 'duplicate'],
        description: '`duplicate` means the event_id already existed and nothing was written.',
      },
    },
  },

  ValidationError: {
    $id: 'ValidationError',
    type: 'object',
    required: ['error', 'issues'],
    properties: {
      error: { type: 'string', enum: ['validation_failed'] },
      issues: {
        type: 'array',
        items: {
          type: 'object',
          required: ['path', 'message'],
          properties: {
            path: { type: 'string', examples: ['payload.path'] },
            message: { type: 'string' },
          },
        },
        description: 'Field paths only. Submitted values are never echoed, since payloads carry secrets.',
      },
    },
  },

  ErrorResponse: {
    $id: 'ErrorResponse',
    type: 'object',
    required: ['error'],
    properties: {
      error: { type: 'string' },
    },
  },
} as const;

/** `401` is identical for a missing and a wrong key, by design. */
const UNAUTHORIZED = {
  description: 'Missing or invalid API key. Identical for both cases, so a caller learns nothing about which.',
  $ref: 'ErrorResponse#',
};

const PAYLOAD_TOO_LARGE = {
  description: 'Body exceeded BODY_LIMIT_BYTES.',
  $ref: 'ErrorResponse#',
};

const STORAGE_UNAVAILABLE = {
  description: 'The database is unreachable.',
  $ref: 'ErrorResponse#',
};

/** Route schema for `POST /v1/events`. */
export const POST_EVENT_SCHEMA = {
  tags: ['events'],
  summary: 'Submit one agent activity event',
  description:
    'Idempotent on `event_id`. A replay returns 200 rather than 409, because a replay is a success from an at-least-once client\'s point of view.',
  security: [{ bearerAuth: [] }],
  body: { $ref: 'EventEnvelope#' },
  response: {
    201: { description: 'Event stored.', $ref: 'IngestResult#' },
    200: { description: 'Already stored; nothing written.', $ref: 'IngestResult#' },
    400: { description: 'Envelope failed validation.', $ref: 'ValidationError#' },
    401: UNAUTHORIZED,
    413: PAYLOAD_TOO_LARGE,
    503: STORAGE_UNAVAILABLE,
  },
} as const;

/** Route schema for `POST /v1/events/batch`. */
export const POST_EVENTS_BATCH_SCHEMA = {
  tags: ['events'],
  summary: 'Submit up to 100 events in one transaction',
  description:
    'All-or-nothing: a failure persists nothing. Returns 207 because a batch can legitimately mix created, duplicate, and rejected outcomes.',
  security: [{ bearerAuth: [] }],
  body: {
    type: 'object',
    required: ['events'],
    properties: {
      events: {
        type: 'array',
        minItems: 1,
        maxItems: 100,
        items: { $ref: 'EventEnvelope#' },
      },
    },
  },
  response: {
    207: {
      description: 'Per-event outcomes, in submission order.',
      type: 'object',
      required: ['results'],
      properties: {
        results: { type: 'array', items: { $ref: 'IngestResult#' } },
        accepted: { type: 'integer' },
        duplicates: { type: 'integer' },
        rejected: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              index: { type: 'integer', description: 'Position in the submitted array.' },
              issues: { type: 'array', items: { type: 'object', additionalProperties: true } },
            },
          },
        },
      },
    },
    400: { description: 'Batch envelope unusable.', $ref: 'ValidationError#' },
    401: UNAUTHORIZED,
    413: PAYLOAD_TOO_LARGE,
    503: STORAGE_UNAVAILABLE,
  },
} as const;

/** Route schema for `GET /healthz`. */
export const HEALTHZ_SCHEMA = {
  tags: ['health'],
  summary: 'Liveness probe',
  description: 'Never touches the database, so a transient outage cannot trigger a restart loop.',
  response: {
    200: {
      description: 'Process is running.',
      type: 'object',
      properties: { status: { type: 'string', enum: ['ok'] } },
    },
  },
} as const;

/** Route schema for `GET /readyz`. */
export const READYZ_SCHEMA = {
  tags: ['health'],
  summary: 'Readiness probe',
  description: 'Probes the database. Re-evaluated per request, so it recovers once the database returns.',
  response: {
    200: {
      description: 'Ready to serve.',
      type: 'object',
      properties: {
        status: { type: 'string', enum: ['ready'] },
        database: { type: 'boolean' },
      },
    },
    503: {
      description: 'Database unreachable.',
      type: 'object',
      properties: {
        status: { type: 'string', enum: ['degraded'] },
        database: { type: 'boolean' },
      },
    },
  },
} as const;
