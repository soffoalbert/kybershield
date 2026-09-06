/**
 * Health and readiness endpoints.
 */

import { describe, it } from 'vitest';

describe('GET /healthz', () => {
  it.todo('answers 200 without authentication');

  it.todo(
    'answers 200 even when the database is down',
    // Liveness must not depend on a dependency, or a transient database outage
    // triggers a pointless restart loop of an otherwise healthy process.
  );
});

describe('GET /readyz', () => {
  it.todo('answers 200 ready when the database responds');

  it.todo('answers 503 degraded when the database is unreachable');

  it.todo('requires no authentication');

  it.todo(
    'recovers to 200 once the database returns',
    // Readiness must be re-evaluated per request rather than cached at boot.
  );
});

describe('unknown routes', () => {
  it.todo('answer 404 with a JSON body rather than HTML');
});
