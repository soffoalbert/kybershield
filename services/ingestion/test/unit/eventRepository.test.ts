/**
 * Repository behaviour against a mocked pg pool.
 *
 * Narrow by design. The real SQL is covered by the integration suite against
 * actual Postgres; mocking a driver only proves the mock behaves as configured.
 * What is worth asserting here is the parameter mapping and the error
 * translation, neither of which needs a database.
 */

import { describe, it } from 'vitest';

describe('PgEventRepository.insertIfAbsent', () => {
  it.todo(
    'reports created when the insert returns a row',
    // ON CONFLICT DO NOTHING with RETURNING yields zero rows on conflict, so
    // rowCount is how a duplicate is detected.
  );

  it.todo('reports duplicate when the insert returns no rows');

  it.todo(
    'passes event fields as positional parameters in schema order',
    // Assert the values array, which catches a silent column reorder that
    // would otherwise write a url into the path column.
  );

  it.todo('serialises payload and raw as JSON');

  it.todo('passes tags as a native array, not a JSON string');

  it.todo(
    'runs the agent upsert and the event insert in one transaction',
    // Assert BEGIN, both statements, then COMMIT on the same client.
  );

  it.todo(
    'rolls back and wraps the driver error in a StorageError',
    // Assert ROLLBACK was issued and the thrown error carries the original
    // as `cause`.
  );

  it.todo(
    'releases the client even when the rollback itself fails',
    // A leaked connection under repeated failure exhausts the pool and turns
    // a transient outage into a permanent one.
  );
});

describe('PgEventRepository.insertBatchIfAbsent', () => {
  it.todo('returns one result per input event, in input order');

  it.todo(
    'collapses duplicate event ids within the batch',
    // ON CONFLICT cannot resolve two conflicting rows inside one statement,
    // so the repeat must be removed before the query runs.
  );

  it.todo('reports the collapsed within-batch repeat as duplicate');

  it.todo('reports a mix of created and duplicate correctly');

  it.todo('persists nothing when the transaction fails');
});

describe('PgEventRepository.upsertAgentSeen', () => {
  it.todo('inserts an unknown agent');

  it.todo(
    'never moves last_seen_at backwards',
    // An out-of-order event carrying an older timestamp must not rewind it.
  );
});

describe('PgEventRepository.healthCheck', () => {
  it.todo('returns true when the probe query succeeds');

  it.todo(
    'returns false rather than throwing when the pool rejects',
    // Lets /readyz answer 503 instead of 500.
  );
});
