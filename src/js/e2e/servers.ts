import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'

// Starts the mock providers and the app for the whole run, and stops them after (a Playwright global setup).
// Playwright's own `webServer` first asks whether each port already answers, and where a closed port is not
// refused but silently dropped (sandboxes, some VPNs) that question waits out a long timeout: minutes per run.
// Asking with a short timeout and starting at once avoids it. A server that already answers is used as it is.

const MOCK = 'http://127.0.0.1:5056'
const APP = 'http://127.0.0.1:5057'
const REPO = '../..'
const ASK_MS = 400 // one question to a server
const START_MS = 60_000 // how long a server may take to come up

interface Server {
  module: string
  args: string[]
  url: string
}
const SERVERS: readonly Server[] = [
  { module: 'tests.mock_providers', args: ['--port', '5056'], url: `${MOCK}/__mock/settings` },
  { module: 'scripts.e2e_app', args: ['--port', '5057', '--mock', MOCK], url: `${APP}/api/auth/status` },
]

async function answers(url: string): Promise<boolean> {
  try {
    await fetch(url, { signal: AbortSignal.timeout(ASK_MS) })
    return true
  } catch {
    return false
  }
}

async function untilUp(server: Server): Promise<void> {
  const deadline = Date.now() + START_MS
  while (Date.now() < deadline) {
    if (await answers(server.url)) return
    await new Promise(done => setTimeout(done, 200))
  }
  throw new Error(`${server.module} did not answer at ${server.url} within ${String(START_MS / 1000)} s`)
}

function launch(server: Server): ChildProcess {
  const args = ['run', '--project', REPO, 'env', 'PYTHONPATH=src/py:.', 'python', '-m', server.module, ...server.args]
  return spawn('uv', args, { cwd: REPO, stdio: 'ignore', detached: true })
}

export default async function globalSetup(): Promise<() => void> {
  const running = await Promise.all(SERVERS.map(async server => ((await answers(server.url)) ? null : launch(server))))
  const stop = (): void => {
    for (const child of running) {
      // The whole group: `uv run` starts the server as its own child
      if (child?.pid) process.kill(-child.pid, 'SIGTERM')
    }
  }
  try {
    await Promise.all(SERVERS.map(untilUp))
  } catch (error) {
    stop()
    throw error
  }
  return stop
}
