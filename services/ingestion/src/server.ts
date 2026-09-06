/**
 * Process entrypoint: load config, wire real dependencies, listen, shut down
 * cleanly on a signal.
 */

import { buildApp, systemClock } from './app.js';
import { EnvApiKeyStore } from './auth/apiKeyStore.js';
import { loadConfig } from './config/env.js';
import { PgEventRepository } from './db/eventRepository.js';
import { createPool } from './db/pool.js';

const config = loadConfig();
const pool = createPool(config);

const app = buildApp({
  config,
  repository: new PgEventRepository(pool),
  apiKeyStore: new EnvApiKeyStore(config.apiKeys),
  clock: systemClock,
});

async function shutdown(signal: string): Promise<void> {
  app.log.info({ signal }, 'shutting down');
  try {
    await app.close();
    await pool.end();
    process.exit(0);
  } catch (error) {
    app.log.error({ error }, 'error during shutdown');
    process.exit(1);
  }
}

for (const signal of ['SIGTERM', 'SIGINT'] as const) {
  process.on(signal, () => void shutdown(signal));
}

try {
  await app.listen({ port: config.port, host: config.host });
} catch (error) {
  app.log.error({ error }, 'failed to start');
  process.exit(1);
}
