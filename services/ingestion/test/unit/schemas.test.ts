/**
 * Envelope validation.
 *
 * The service's first line of defence: everything here runs before any
 * database work, so a malformed body is rejected cheaply.
 */

import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import { parseEnvelope, toValidationError } from '../../src/schemas/event.js';
import { buildEnvelope } from '../helpers/fakes.js';

/** The issue paths from a failed parse, for asserting on rejections. */
function issuePaths(body: unknown): string[] {
  const result = parseEnvelope(body, 'test-client');
  if (result.ok) {
    throw new Error('expected the envelope to be rejected');
  }
  return result.error.issues.map((issue) => issue.path);
}

describe('parseEnvelope', () => {
  it('accepts a well-formed envelope and maps it to an AgentEvent', () => {
    const body = buildEnvelope();

    const result = parseEnvelope(body, 'test-client');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.eventId).toBe('evt-2f9a1c');
    expect(result.value.agentId).toBe('agent-alpha');
    expect(result.value.type).toBe('file_read');
    expect(result.value.occurredAt).toBeInstanceOf(Date);
    expect(result.value.occurredAt.toISOString()).toBe('2026-08-25T12:00:00.000Z');
    expect(result.value.clientId).toBe('test-client');
  });

  it('takes clientId from the argument, not the body', () => {
    // A body carrying its own client_id must not override the authenticated
    // identity, or a client could forge attribution for another tenant.
    const result = parseEnvelope(buildEnvelope({ client_id: 'malicious' }), 'test-client');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.clientId).toBe('test-client');
  });

  it('rejects a missing event_id', () => {
    const { event_id, ...body } = buildEnvelope();

    expect(issuePaths(body)).toContain('event_id');
  });

  it('rejects a blank event_id', () => {
    expect(issuePaths(buildEnvelope({ event_id: '' }))).toContain('event_id');
  });

  it('rejects a missing agent_id', () => {
    const { agent_id, ...body } = buildEnvelope();

    expect(issuePaths(body)).toContain('agent_id');
  });

  it('rejects a timestamp with no timezone offset', () => {
    // '2026-08-25T12:00:00' is ambiguous. Accepting it would silently corrupt
    // the ordering the timeline and the rapid-reads rule depend on.
    expect(issuePaths(buildEnvelope({ timestamp: '2026-08-25T12:00:00' }))).toContain('timestamp');
  });

  it('rejects a non-ISO timestamp such as "yesterday"', () => {
    expect(issuePaths(buildEnvelope({ timestamp: 'yesterday' }))).toContain('timestamp');
  });

  it('accepts a timestamp with a non-UTC offset and normalises it', () => {
    const result = parseEnvelope(
      buildEnvelope({ timestamp: '2026-08-25T14:00:00+02:00' }),
      'test-client',
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.occurredAt.toISOString()).toBe('2026-08-25T12:00:00.000Z');
  });

  it('accepts an unknown event type and stores its payload verbatim', () => {
    // Agents gain capabilities faster than this service deploys, so an
    // unrecognised type must not be a rejection.
    const payload = { anything: 'goes', nested: { deeply: true } };

    const result = parseEnvelope(
      buildEnvelope({ type: 'quantum_teleport', payload }),
      'test-client',
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.type).toBe('quantum_teleport');
    expect(result.value.payload).toStrictEqual(payload);
  });

  it('validates a known type against its payload schema', () => {
    // A file_read with no path is a client bug worth reporting, not a
    // passthrough.
    expect(issuePaths(buildEnvelope({ type: 'file_read', payload: {} }))).toContain('payload.path');
  });

  it('preserves unrecognised fields inside a known payload', () => {
    // Passthrough, so the analyser can use a field before ingestion knows it.
    const result = parseEnvelope(
      buildEnvelope({
        type: 'http_request',
        payload: { method: 'GET', url: 'https://example.com', trace_id: 'abc' },
      }),
      'test-client',
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.payload).toStrictEqual({
      method: 'GET',
      url: 'https://example.com',
      trace_id: 'abc',
    });
  });

  it('sets raw to the exact submitted body', () => {
    // This is the forensic-fidelity guarantee: raw survives even where payload
    // was normalised.
    const body = buildEnvelope({
      type: 'http_request',
      payload: { method: 'GET', url: 'https://example.com' },
      tags: ['audit'],
    });

    const result = parseEnvelope(body, 'test-client');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.raw).toStrictEqual(body);
  });

  it('defaults tags to an empty array when absent', () => {
    const { tags, ...body } = buildEnvelope();

    const result = parseEnvelope(body, 'test-client');

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.tags).toStrictEqual([]);
  });

  it('rejects more than 50 tags', () => {
    const tags = Array.from({ length: 51 }, (_, index) => `tag-${index}`);

    expect(issuePaths(buildEnvelope({ tags }))).toContain('tags');
  });

  it('rejects a payload that is not an object', () => {
    expect(issuePaths(buildEnvelope({ payload: 'not-an-object' }))).toContain('payload');
    expect(issuePaths(buildEnvelope({ payload: [1, 2, 3] }))).toContain('payload');
  });

  it('reports every failing field at once, not just the first', () => {
    const paths = issuePaths({ type: 'file_read', payload: { path: '/tmp/x' } });

    expect(paths).toContain('event_id');
    expect(paths).toContain('agent_id');
    expect(paths).toContain('timestamp');
  });
});

describe('toValidationError', () => {
  it('flattens nested zod paths into dotted strings', () => {
    const schema = z.object({ outer: z.object({ inner: z.string() }) });
    const parsed = schema.safeParse({ outer: { inner: 42 } });

    expect(parsed.success).toBe(false);
    if (parsed.success) return;
    expect(toValidationError(parsed.error).issues[0]?.path).toBe('outer.inner');
  });

  it('prefixes paths when given a root', () => {
    const schema = z.object({ path: z.string() });
    const parsed = schema.safeParse({});

    expect(parsed.success).toBe(false);
    if (parsed.success) return;
    expect(toValidationError(parsed.error, ['payload']).issues[0]?.path).toBe('payload.path');
  });

  it('never includes submitted values in the issue text', () => {
    // Payloads routinely carry secrets and this output reaches both the
    // response and the logs.
    const schema = z.object({ token: z.number() });
    const parsed = schema.safeParse({ token: 'sk-live-super-secret' });

    expect(parsed.success).toBe(false);
    if (parsed.success) return;
    const serialised = JSON.stringify(toValidationError(parsed.error));
    expect(serialised).not.toContain('sk-live-super-secret');
  });
});
