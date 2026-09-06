/**
 * Configuration parsing.
 *
 * Boot-time validation, so every failure here is one the operator sees
 * immediately rather than on the first request.
 */

import { describe, it } from 'vitest';

describe('parseApiKeys', () => {
  it.todo(
    'parses a single id:secret pair into a secret-keyed map',
    // Keyed by secret because lookup happens by presented secret.
  );

  it.todo('parses several comma-separated pairs');

  it.todo('trims whitespace around ids and secrets');

  it.todo('throws on an entry with no colon');

  it.todo('throws on a blank secret such as "client:"');

  it.todo('throws on a blank client id such as ":secret"');

  it.todo(
    'throws when two clients share a secret',
    // A shared secret makes the map ambiguous and silently misattributes
    // events to whichever entry parsed last.
  );

  it.todo(
    'accepts a secret containing a colon',
    // Split on the first colon only, so base64 or URL-shaped secrets survive.
  );
});

describe('loadConfig', () => {
  it.todo('returns a config when every required variable is present');

  it.todo('throws when DATABASE_URL is absent');

  it.todo('throws when API_KEYS is absent');

  it.todo('applies defaults for optional variables');

  it.todo('coerces numeric strings to numbers');

  it.todo('throws on a non-numeric PORT');

  it.todo('throws on an unrecognised LOG_LEVEL');

  it.todo(
    'reads from the injected source rather than process.env',
    // Keeps the suite free of global environment mutation.
  );
});
