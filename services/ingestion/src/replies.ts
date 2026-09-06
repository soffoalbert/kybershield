/**
 * The error envelope, in one place.
 *
 * Every failure this service reports is `{error, issues?}` — a stable slug a
 * client can branch on, plus the offending field names. It was previously
 * spelled out at each of the five places that send it, which is five chances
 * for the shape to drift from the one documented in `schemas/openapi.ts`.
 */

import type { FastifyReply } from 'fastify';
import type { ValidationIssue } from './domain/types.js';

/**
 * Reply `400 {error:"validation_failed", issues}`.
 *
 * Issues carry paths and messages only, never values: event payloads
 * routinely contain secrets, and an error body is the easiest place to leak
 * one by accident.
 */
export function replyValidationFailed(reply: FastifyReply, issues: ValidationIssue[]): void {
  reply.code(400).send({ error: 'validation_failed', issues });
}
