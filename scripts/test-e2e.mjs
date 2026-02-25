#!/usr/bin/env node
// Comprehensive end-to-end tests for all Conclave services.
// Tests connectivity, read/write integration via API, web UI, and container skills.
//
// Usage:
//   node scripts/test-e2e.mjs [--minimal] [--test-ollama] [--json]
//
// Flags:
//   --minimal      Skip services not in the minimal image (Matrix, Element, Planka, Ollama, Pushgateway)
//   --test-ollama  Opt-in to Ollama generation test (requires a model loaded)
//   --json         Write structured JSON results to /tmp/conclave-test-results.json

import { chromium } from 'playwright';
import { mkdirSync, readFileSync, writeFileSync } from 'fs';
import { execSync, execFileSync } from 'child_process';
import { randomUUID } from 'crypto';
import { createConnection } from 'net';

const BASE = 'http://localhost:8888';
const SCREENSHOT_DIR = '/tmp/conclave-screenshots';
mkdirSync(SCREENSHOT_DIR, { recursive: true });

const args = process.argv.slice(2);
const MINIMAL = args.includes('--minimal');
const TEST_OLLAMA = args.includes('--test-ollama');
const JSON_OUTPUT = args.includes('--json');
const MODE = MINIMAL ? 'minimal' : 'full';

// ── Container runtime detection ──────────────────────────────────────────────

function detectRuntime() {
  for (const cmd of ['docker', 'podman', 'nerdctl', 'sudo docker', 'sudo podman', 'sudo nerdctl']) {
    try {
      execSync(`${cmd} inspect conclave-dev`, { encoding: 'utf8', timeout: 5000, stdio: 'pipe' });
      return cmd;
    } catch {}
  }
  return 'docker';
}

const CTR = detectRuntime();

function containerExec(command, { timeout = 15000 } = {}) {
  // Use execFileSync to avoid host shell expanding $VAR references in the command
  const ctrParts = CTR.split(' ');
  try {
    return execFileSync(ctrParts[0], [...ctrParts.slice(1), 'exec', 'conclave-dev', 'bash', '-c', command], {
      encoding: 'utf8',
      timeout,
      stdio: 'pipe',
    }).trim();
  } catch (err) {
    const stderr = err.stderr ? err.stderr.toString().trim() : '';
    throw new Error(stderr || err.message.split('\n')[0]);
  }
}

// Run a skill command inside the container using the baked-in helper script.
// The helper loads agent-env.sh, cd's into the skill dir, and exec's the command.
// Arguments are passed as separate OS args, avoiding shell quoting issues.
function skillExec(skillDir, cmdArgs, { timeout = 20000 } = {}) {
  const ctrParts = CTR.split(' ');
  try {
    return execFileSync(ctrParts[0], [
      ...ctrParts.slice(1), 'exec', 'conclave-dev',
      'bash', '/opt/conclave/scripts/e2e-skill-test.sh', skillDir, ...cmdArgs,
    ], {
      encoding: 'utf8',
      timeout,
      stdio: 'pipe',
    }).trim();
  } catch (err) {
    const stderr = err.stderr ? err.stderr.toString().trim() : '';
    throw new Error(stderr || err.message.split('\n')[0]);
  }
}

// ── Credential retrieval ─────────────────────────────────────────────────────

function getSecret(name) {
  if (process.env[name]) return process.env[name];
  try {
    const out = containerExec(`grep '^${name}=' /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2`);
    if (out) return out;
  } catch {}
  // Fallback: check agent-env.sh (some vars like MATRIX_SERVER_NAME live there)
  try {
    const out = containerExec(`grep '^${name}=' /workspace/config/agent-env.sh 2>/dev/null | cut -d= -f2`);
    if (out) return out;
  } catch {}
  return '';
}

const ADMIN_PASS = getSecret('CONCLAVE_ADMIN_PASSWORD') || 'admin';
const AGENT_PASS = getSecret('CONCLAVE_AGENT_PASSWORD') || '';
const CHROMADB_TOKEN = getSecret('CHROMADB_TOKEN') || '';
const MATRIX_SERVER_NAME = getSecret('MATRIX_SERVER_NAME') || getSecret('AGENT_MATRIX_SERVER_NAME') || 'conclave.local';
const ADMIN_USER = 'admin';

// ── Test results collection ──────────────────────────────────────────────────

const results = [];

function record(group, name, status, detail = '', durationMs = 0) {
  const icon = status === 'pass' ? 'PASS' : status === 'skip' ? 'SKIP' : 'FAIL';
  console.log(`  [${icon}] ${group}/${name}: ${detail}`);
  results.push({ group, name, status, duration_ms: durationMs, detail });
}

function skip(group, name, reason = 'minimal mode') {
  record(group, name, 'skip', reason);
}

// ── HTTP helpers (no Playwright needed) ──────────────────────────────────────

async function httpGet(url, { headers = {}, auth } = {}) {
  const h = { ...headers };
  if (auth) h['Authorization'] = 'Basic ' + Buffer.from(`${auth.user}:${auth.pass}`).toString('base64');
  const resp = await fetch(url, { headers: h });
  return resp;
}

async function httpPost(url, body, { headers = {}, auth } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers };
  if (auth) h['Authorization'] = 'Basic ' + Buffer.from(`${auth.user}:${auth.pass}`).toString('base64');
  const resp = await fetch(url, { method: 'POST', headers: h, body: JSON.stringify(body) });
  return resp;
}

async function httpDelete(url, { headers = {}, auth } = {}) {
  const h = { ...headers };
  if (auth) h['Authorization'] = 'Basic ' + Buffer.from(`${auth.user}:${auth.pass}`).toString('base64');
  const resp = await fetch(url, { method: 'DELETE', headers: h });
  return resp;
}

async function httpPut(url, body, { headers = {}, auth } = {}) {
  const h = { 'Content-Type': 'application/json', ...headers };
  if (auth) h['Authorization'] = 'Basic ' + Buffer.from(`${auth.user}:${auth.pass}`).toString('base64');
  const resp = await fetch(url, { method: 'PUT', headers: h, body: typeof body === 'string' ? body : JSON.stringify(body) });
  return resp;
}

// Push text body (for pushgateway)
async function httpPostText(url, text, { auth } = {}) {
  const h = { 'Content-Type': 'text/plain' };
  if (auth) h['Authorization'] = 'Basic ' + Buffer.from(`${auth.user}:${auth.pass}`).toString('base64');
  return fetch(url, { method: 'POST', headers: h, body: text });
}

// ── Timed test runner ────────────────────────────────────────────────────────

async function runTest(group, name, fn, { fullOnly = false } = {}) {
  if (fullOnly && MINIMAL) {
    skip(group, name);
    return;
  }
  const t0 = Date.now();
  try {
    await fn();
  } catch (err) {
    record(group, name, 'fail', err.message.split('\n')[0], Date.now() - t0);
  }
}

// ── TCP check helper ─────────────────────────────────────────────────────────

function tcpCheck(host, port, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const sock = createConnection({ host, port }, () => {
      sock.destroy();
      resolve();
    });
    sock.setTimeout(timeoutMs);
    sock.on('timeout', () => { sock.destroy(); reject(new Error('timeout')); });
    sock.on('error', reject);
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// TEST GROUPS
// ═══════════════════════════════════════════════════════════════════════════════

// ── 1. Dashboard ─────────────────────────────────────────────────────────────

async function testDashboard(browser) {
  console.log('\n── Dashboard ──');
  await runTest('dashboard', 'load', async () => {
    const t0 = Date.now();
    const context = await browser.newContext({
      httpCredentials: { username: ADMIN_USER, password: ADMIN_PASS },
    });
    const page = await context.newPage();
    try {
      await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 15000 });
      const heading = await page.textContent('h1');
      if (heading && heading.includes('Conclave')) {
        record('dashboard', 'load', 'pass', `h1="${heading}"`, Date.now() - t0);
      } else {
        record('dashboard', 'load', 'fail', `unexpected h1="${heading}"`, Date.now() - t0);
      }
    } finally {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/dashboard.png` }).catch(() => {});
      await context.close();
    }
  });
}

// ── 2. nginx auth ────────────────────────────────────────────────────────────

async function testNginx() {
  console.log('\n── nginx ──');

  await runTest('nginx', 'reject-no-auth', async () => {
    const t0 = Date.now();
    const resp = await fetch(`${BASE}/`, { redirect: 'manual' });
    if (resp.status === 401) {
      record('nginx', 'reject-no-auth', 'pass', 'HTTP 401 without credentials', Date.now() - t0);
    } else {
      record('nginx', 'reject-no-auth', 'fail', `expected 401, got ${resp.status}`, Date.now() - t0);
    }
  });

  await runTest('nginx', 'accept-with-auth', async () => {
    const t0 = Date.now();
    const resp = await httpGet(`${BASE}/`, { auth: { user: ADMIN_USER, pass: ADMIN_PASS } });
    if (resp.ok) {
      record('nginx', 'accept-with-auth', 'pass', `HTTP ${resp.status} with credentials`, Date.now() - t0);
    } else {
      record('nginx', 'accept-with-auth', 'fail', `HTTP ${resp.status}`, Date.now() - t0);
    }
  });
}

// ── 3. Matrix / Synapse ──────────────────────────────────────────────────────

async function testMatrix(browser) {
  console.log('\n── Matrix / Synapse ──');

  // existing: versions
  await runTest('matrix', 'api-versions', async () => {
    const t0 = Date.now();
    const resp = await httpGet(`${BASE}/_matrix/client/versions`);
    const data = await resp.json();
    if (data.versions && data.versions.length > 0) {
      record('matrix', 'api-versions', 'pass', `${data.versions.length} versions`, Date.now() - t0);
    } else {
      record('matrix', 'api-versions', 'fail', 'no versions returned', Date.now() - t0);
    }
  }, { fullOnly: true });

  // API write: login + send message
  let accessToken = '';
  let roomId = '';
  const testMsg = `e2e-test-${randomUUID().slice(0, 8)}`;

  await runTest('matrix', 'api-login', async () => {
    const t0 = Date.now();
    const resp = await httpPost(`${BASE}/_matrix/client/v3/login`, {
      type: 'm.login.password',
      identifier: { type: 'm.id.user', user: ADMIN_USER },
      password: ADMIN_PASS,
    });
    const data = await resp.json();
    if (data.access_token) {
      accessToken = data.access_token;
      record('matrix', 'api-login', 'pass', `user_id=${data.user_id}`, Date.now() - t0);
    } else {
      record('matrix', 'api-login', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Resolve #home room alias
  await runTest('matrix', 'api-resolve-room', async () => {
    if (!accessToken) throw new Error('no access token');
    const t0 = Date.now();
    const alias = encodeURIComponent(`#home:${MATRIX_SERVER_NAME}`);
    const resp = await httpGet(`${BASE}/_matrix/client/v3/directory/room/${alias}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const data = await resp.json();
    if (data.room_id) {
      roomId = data.room_id;
      record('matrix', 'api-resolve-room', 'pass', `room_id=${roomId}`, Date.now() - t0);
    } else {
      record('matrix', 'api-resolve-room', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Send message
  let eventId = '';
  await runTest('matrix', 'api-send-message', async () => {
    if (!accessToken || !roomId) throw new Error('no token or room');
    const t0 = Date.now();
    const txnId = randomUUID();
    const resp = await httpPut(
      `${BASE}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${txnId}`,
      { msgtype: 'm.text', body: testMsg },
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    const data = await resp.json();
    if (data.event_id) {
      eventId = data.event_id;
      record('matrix', 'api-send-message', 'pass', `event_id=${eventId}`, Date.now() - t0);
    } else {
      record('matrix', 'api-send-message', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Read back message
  await runTest('matrix', 'api-read-messages', async () => {
    if (!accessToken || !roomId) throw new Error('no token or room');
    const t0 = Date.now();
    const resp = await httpGet(
      `${BASE}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/messages?dir=b&limit=10`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    const data = await resp.json();
    const found = data.chunk?.some(e => e.content?.body === testMsg);
    if (found) {
      record('matrix', 'api-read-messages', 'pass', 'sent message found in room', Date.now() - t0);
    } else {
      record('matrix', 'api-read-messages', 'fail', 'sent message not found in last 10 messages', Date.now() - t0);
    }
  }, { fullOnly: true });

  // Skill write (unified matrix skill — send subcommand)
  const skillMsg = `e2e-skill-${randomUUID().slice(0, 8)}`;
  await runTest('matrix', 'skill-send', async () => {
    const t0 = Date.now();
    const out = skillExec('/opt/conclave/pi/skills/matrix', [
      'python3', 'matrix.py', 'send', skillMsg, '--room', 'home',
    ], { timeout: 30000 });
    if (out.includes('Sent') || out.includes('event') || out.includes('Event ID')) {
      record('matrix', 'skill-send', 'pass', out.slice(0, 80) || 'message sent', Date.now() - t0);
    } else {
      record('matrix', 'skill-send', 'fail', out.slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Skill read (unified matrix skill — read subcommand)
  await runTest('matrix', 'skill-read', async () => {
    const t0 = Date.now();
    const out = skillExec('/opt/conclave/pi/skills/matrix', [
      'python3', 'matrix.py', 'read', '--room', 'home', '--json', '--since', '5',
    ], { timeout: 30000 });
    if (out.includes(skillMsg)) {
      record('matrix', 'skill-read', 'pass', 'skill message found', Date.now() - t0);
    } else {
      record('matrix', 'skill-read', 'fail', `message "${skillMsg}" not found in output`, Date.now() - t0);
    }
  }, { fullOnly: true });

  // Element Web
  await runTest('matrix', 'element-web', async () => {
    const t0 = Date.now();
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await page.goto(`${BASE}/element/`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(3000);
      const title = await page.title();
      if (title.includes('Element')) {
        record('matrix', 'element-web', 'pass', `title="${title}"`, Date.now() - t0);
      } else {
        record('matrix', 'element-web', 'fail', `title="${title}"`, Date.now() - t0);
      }
    } finally {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/element-web.png` }).catch(() => {});
      await context.close();
    }
  }, { fullOnly: true });
}

// ── 4. ChromaDB ──────────────────────────────────────────────────────────────

async function testChromaDB() {
  console.log('\n── ChromaDB ──');

  const chromaAuth = CHROMADB_TOKEN
    ? { headers: { Authorization: `Bearer ${CHROMADB_TOKEN}` } }
    : {};

  // Heartbeat
  await runTest('chromadb', 'heartbeat', async () => {
    const t0 = Date.now();
    // Use the nginx path (no auth) which proxies to chromadb
    const resp = await httpGet(`${BASE}/chromadb/api/v2/heartbeat`, chromaAuth);
    const text = await resp.text();
    if (text.includes('heartbeat')) {
      record('chromadb', 'heartbeat', 'pass', text.trim().slice(0, 80), Date.now() - t0);
    } else {
      record('chromadb', 'heartbeat', 'fail', `unexpected: ${text.slice(0, 80)}`, Date.now() - t0);
    }
  });

  const collectionName = `test-e2e-${randomUUID().slice(0, 8)}`;
  const docId = `test-${randomUUID().slice(0, 8)}`;
  let collectionId = '';

  // API write: create collection + add document
  await runTest('chromadb', 'api-create-collection', async () => {
    const t0 = Date.now();
    const resp = await fetch(`${BASE}/chromadb/api/v2/tenants/default_tenant/databases/default_database/collections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(CHROMADB_TOKEN ? { Authorization: `Bearer ${CHROMADB_TOKEN}` } : {}) },
      body: JSON.stringify({ name: collectionName, metadata: { source: 'e2e-test' } }),
    });
    const data = await resp.json();
    if (data.id) {
      collectionId = data.id;
      record('chromadb', 'api-create-collection', 'pass', `id=${collectionId}`, Date.now() - t0);
    } else {
      record('chromadb', 'api-create-collection', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
    }
  });

  // Use a simple 3D embedding vector for testing
  const testEmbedding = [0.1, 0.2, 0.3];

  await runTest('chromadb', 'api-add-document', async () => {
    if (!collectionId) throw new Error('no collection');
    const t0 = Date.now();
    const resp = await fetch(`${BASE}/chromadb/api/v2/tenants/default_tenant/databases/default_database/collections/${collectionId}/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(CHROMADB_TOKEN ? { Authorization: `Bearer ${CHROMADB_TOKEN}` } : {}) },
      body: JSON.stringify({
        ids: [docId],
        documents: ['conclave e2e test document'],
        metadatas: [{ source: 'e2e-test' }],
        embeddings: [testEmbedding],
      }),
    });
    if (resp.ok) {
      record('chromadb', 'api-add-document', 'pass', `doc_id=${docId}`, Date.now() - t0);
    } else {
      const text = await resp.text();
      record('chromadb', 'api-add-document', 'fail', text.slice(0, 120), Date.now() - t0);
    }
  });

  // API read: query collection
  await runTest('chromadb', 'api-query', async () => {
    if (!collectionId) throw new Error('no collection');
    const t0 = Date.now();
    const resp = await fetch(`${BASE}/chromadb/api/v2/tenants/default_tenant/databases/default_database/collections/${collectionId}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(CHROMADB_TOKEN ? { Authorization: `Bearer ${CHROMADB_TOKEN}` } : {}) },
      body: JSON.stringify({
        query_embeddings: [testEmbedding],
        n_results: 1,
        include: ['documents', 'metadatas'],
      }),
    });
    const data = await resp.json();
    const found = data.ids?.[0]?.includes(docId);
    if (found) {
      record('chromadb', 'api-query', 'pass', 'document found via query', Date.now() - t0);
    } else {
      record('chromadb', 'api-query', 'fail', `doc not found: ${JSON.stringify(data).slice(0, 120)}`, Date.now() - t0);
    }
  });

  // Skill tests use a separate collection (no pre-set embedding dimension)
  const skillCollectionName = `test-skill-${randomUUID().slice(0, 8)}`;
  const skillDocId = `test-skill-${randomUUID().slice(0, 8)}`;
  await runTest('chromadb', 'skill-add', async () => {
    const t0 = Date.now();
    const out = skillExec('/opt/conclave/pi/skills/chromadb', [
      'python3', 'query.py', 'add',
      '--collection', skillCollectionName,
      '--id', skillDocId,
      '--text', 'conclave skill e2e test',
    ]);
    record('chromadb', 'skill-add', 'pass', out.slice(0, 80) || 'document added via skill', Date.now() - t0);
  });

  // Skill read
  await runTest('chromadb', 'skill-query', async () => {
    const t0 = Date.now();
    const out = skillExec('/opt/conclave/pi/skills/chromadb', [
      'python3', 'query.py', 'query',
      'conclave skill e2e test',
      '--collection', skillCollectionName,
      '--limit', '1',
    ]);
    if (out.includes(skillDocId) || out.includes('conclave skill e2e test')) {
      record('chromadb', 'skill-query', 'pass', 'skill document found', Date.now() - t0);
    } else {
      record('chromadb', 'skill-query', 'fail', `not found in: ${out.slice(0, 120)}`, Date.now() - t0);
    }
  });

  // Cleanup — delete both API and skill collections
  await runTest('chromadb', 'api-cleanup', async () => {
    const t0 = Date.now();
    const authHeaders = CHROMADB_TOKEN ? { Authorization: `Bearer ${CHROMADB_TOKEN}` } : {};
    const deleted = [];
    for (const name of [collectionName, skillCollectionName]) {
      const resp = await fetch(`${BASE}/chromadb/api/v2/tenants/default_tenant/databases/default_database/collections/${name}`, {
        method: 'DELETE',
        headers: authHeaders,
      });
      if (resp.ok) deleted.push(name);
    }
    record('chromadb', 'api-cleanup', 'pass', `deleted ${deleted.length} collection(s)`, Date.now() - t0);
  });
}

// ── 5. Planka ────────────────────────────────────────────────────────────────

async function testPlanka(browser) {
  console.log('\n── Planka ──');

  // Browser login flow (existing, keep both localhost + 127.0.0.1)
  for (const [host, label] of [['localhost', 'Planka-localhost-1337'], ['127.0.0.1', 'Planka-127.0.0.1-1337']]) {
    await runTest('planka', `browser-login-${host}`, async () => {
      const t0 = Date.now();
      await testPlankaFullLogin(browser, `http://${host}:1337`, label, t0);
    }, { fullOnly: true });
  }

  // API login + write/read
  let plankaToken = '';

  await runTest('planka', 'api-login', async () => {
    const t0 = Date.now();
    const resp = await httpPost('http://localhost:1337/api/access-tokens', {
      emailOrUsername: ADMIN_USER,
      password: ADMIN_PASS,
    });
    const data = await resp.json();
    if (data.item) {
      plankaToken = data.item;
      record('planka', 'api-login', 'pass', 'token obtained', Date.now() - t0);
    } else if (data.pendingToken) {
      // Need to accept terms first
      const termsResp = await fetch('http://localhost:1337/api/terms', {
        headers: { Authorization: `Bearer ${data.pendingToken}` },
      });
      const termsData = await termsResp.json();
      const signature = termsData.item?.signature;
      if (signature) {
        const acceptResp = await httpPost('http://localhost:1337/api/access-tokens/accept-terms', {
          pendingToken: data.pendingToken,
          signature,
        });
        const acceptData = await acceptResp.json();
        if (acceptData.item) {
          plankaToken = acceptData.item;
          record('planka', 'api-login', 'pass', 'token obtained (after terms)', Date.now() - t0);
        } else {
          record('planka', 'api-login', 'fail', 'terms acceptance failed', Date.now() - t0);
        }
      } else {
        record('planka', 'api-login', 'fail', 'no signature in terms', Date.now() - t0);
      }
    } else {
      record('planka', 'api-login', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Find the first project -> board -> list
  let boardId = '';
  let listId = '';
  await runTest('planka', 'api-get-board', async () => {
    if (!plankaToken) throw new Error('no planka token');
    const t0 = Date.now();
    // Get projects first
    const projResp = await fetch('http://localhost:1337/api/projects', {
      headers: { Authorization: `Bearer ${plankaToken}` },
    });
    const projData = await projResp.json();
    const projects = projData.items || [];
    if (projects.length === 0) {
      record('planka', 'api-get-board', 'fail', 'no projects found', Date.now() - t0);
      return;
    }
    // Get project details to find boards
    const projDetailResp = await fetch(`http://localhost:1337/api/projects/${projects[0].id}`, {
      headers: { Authorization: `Bearer ${plankaToken}` },
    });
    const projDetail = await projDetailResp.json();
    const boards = projDetail.included?.boards || [];
    if (boards.length === 0) {
      record('planka', 'api-get-board', 'fail', 'no boards in project', Date.now() - t0);
      return;
    }
    boardId = boards[0].id;
    // Get board details to find lists
    const boardResp = await fetch(`http://localhost:1337/api/boards/${boardId}`, {
      headers: { Authorization: `Bearer ${plankaToken}` },
    });
    const boardData = await boardResp.json();
    const lists = boardData.included?.lists || [];
    if (lists.length > 0) {
      listId = lists[0].id;
      record('planka', 'api-get-board', 'pass', `board=${boardId}, list=${listId}`, Date.now() - t0);
    } else {
      record('planka', 'api-get-board', 'fail', 'no lists on board', Date.now() - t0);
    }
  }, { fullOnly: true });

  // Create a card
  const cardTitle = `E2E Test Card ${randomUUID().slice(0, 8)}`;
  let cardId = '';
  await runTest('planka', 'api-create-card', async () => {
    if (!plankaToken || !listId) throw new Error('no token or list');
    const t0 = Date.now();
    const resp = await fetch(`http://localhost:1337/api/lists/${listId}/cards`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${plankaToken}` },
      body: JSON.stringify({ name: cardTitle, position: 0, type: 'story' }),
    });
    const data = await resp.json();
    if (data.item?.id) {
      cardId = data.item.id;
      record('planka', 'api-create-card', 'pass', `card_id=${cardId}`, Date.now() - t0);
    } else {
      record('planka', 'api-create-card', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Read back card
  await runTest('planka', 'api-read-card', async () => {
    if (!plankaToken || !cardId) throw new Error('no token or card');
    const t0 = Date.now();
    const resp = await fetch(`http://localhost:1337/api/cards/${cardId}`, {
      headers: { Authorization: `Bearer ${plankaToken}` },
    });
    const data = await resp.json();
    if (data.item?.name === cardTitle) {
      record('planka', 'api-read-card', 'pass', `name="${cardTitle}"`, Date.now() - t0);
    } else {
      record('planka', 'api-read-card', 'fail', `name mismatch: ${JSON.stringify(data).slice(0, 120)}`, Date.now() - t0);
    }
  }, { fullOnly: true });

  // Skill write — source admin credentials from container secrets since the agent user
  // may be too short for Planka's username validation (minimum 3 characters).
  // Also set PLANKA_BOARDS with the discovered board ID since agent-env.sh doesn't include it.
  const skillCardTitle = `E2E Skill Card ${randomUUID().slice(0, 8)}`;
  const boardsJson = boardId ? `{"main":"${boardId}"}` : '{}';
  const plankaSkillPreamble = `set -a && source /workspace/config/agent-env.sh && source /workspace/config/generated-secrets.env && set +a && export AGENT_PLANKA_USER=admin && export AGENT_PLANKA_PASSWORD="$CONCLAVE_ADMIN_PASSWORD" && export PLANKA_BOARDS='${boardsJson}'`;
  await runTest('planka', 'skill-create', async () => {
    const t0 = Date.now();
    const out = containerExec(
      `${plankaSkillPreamble} && cd /opt/conclave/pi/skills/planka && python3 planka.py --board main create --list "To Do" --title "${skillCardTitle}"`,
      { timeout: 20000 },
    );
    if (out.includes(skillCardTitle) || out.includes('Created') || out.includes('id')) {
      record('planka', 'skill-create', 'pass', out.slice(0, 80) || 'card created', Date.now() - t0);
    } else {
      record('planka', 'skill-create', 'fail', out.slice(0, 120), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Skill read
  await runTest('planka', 'skill-list', async () => {
    const t0 = Date.now();
    const out = containerExec(
      `${plankaSkillPreamble} && cd /opt/conclave/pi/skills/planka && python3 planka.py --board main list`,
      { timeout: 20000 },
    );
    if (out.includes(skillCardTitle)) {
      record('planka', 'skill-list', 'pass', 'skill card found in list', Date.now() - t0);
    } else {
      record('planka', 'skill-list', 'fail', `card "${skillCardTitle}" not in output`, Date.now() - t0);
    }
  }, { fullOnly: true });

  // Web verify: check card appears in browser
  await runTest('planka', 'web-verify-card', async () => {
    if (!cardId || !boardId) throw new Error('no card or board to verify');
    const t0 = Date.now();
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      // Login
      await page.goto('http://localhost:1337/', { waitUntil: 'networkidle', timeout: 20000 });
      await page.waitForTimeout(2000);

      const loginForm = await page.$('input[name="emailOrUsername"]');
      if (loginForm) {
        await page.fill('input[name="emailOrUsername"]', ADMIN_USER);
        await page.fill('input[name="password"]', ADMIN_PASS);
        await page.press('input[name="password"]', 'Enter');
        await page.waitForTimeout(5000);
      }

      // Navigate to the specific board page
      await page.goto(`http://localhost:1337/boards/${boardId}`, { waitUntil: 'networkidle', timeout: 20000 });
      await page.waitForTimeout(3000);

      // Check for card title on the page
      const content = await page.textContent('body');
      if (content.includes(cardTitle)) {
        record('planka', 'web-verify-card', 'pass', 'card visible in browser', Date.now() - t0);
      } else {
        record('planka', 'web-verify-card', 'fail', 'card not visible in browser', Date.now() - t0);
      }
    } finally {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/planka-card-verify.png` }).catch(() => {});
      await context.close();
    }
  }, { fullOnly: true });

  // Cleanup: delete test cards via API
  await runTest('planka', 'api-cleanup', async () => {
    if (!plankaToken) throw new Error('no token');
    const t0 = Date.now();
    let deleted = 0;
    if (cardId) {
      await fetch(`http://localhost:1337/api/cards/${cardId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${plankaToken}` },
      });
      deleted++;
    }
    // Also find and delete skill-created card
    if (boardId) {
      const boardResp = await fetch(`http://localhost:1337/api/boards/${boardId}`, {
        headers: { Authorization: `Bearer ${plankaToken}` },
      });
      const boardData = await boardResp.json();
      const cards = boardData.included?.cards || [];
      for (const c of cards) {
        if (c.name === skillCardTitle) {
          await fetch(`http://localhost:1337/api/cards/${c.id}`, {
            method: 'DELETE',
            headers: { Authorization: `Bearer ${plankaToken}` },
          });
          deleted++;
        }
      }
    }
    record('planka', 'api-cleanup', 'pass', `deleted ${deleted} test card(s)`, Date.now() - t0);
  }, { fullOnly: true });
}

// Planka full login helper (carried over from original)
async function testPlankaFullLogin(browser, urlBase, label, t0) {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setViewportSize({ width: 1280, height: 800 });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

  try {
    await page.goto(`${urlBase}/`, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    await page.fill('input[name="emailOrUsername"]', ADMIN_USER);
    await page.fill('input[name="password"]', ADMIN_PASS);
    await page.press('input[name="password"]', 'Enter');
    await page.waitForTimeout(5000);

    let url = page.url();

    // Handle terms page if present
    const termsVisible = await page.$('text=End User Terms');
    if (termsVisible) {
      const safeName = label.replace(/[^a-z0-9-]/gi, '_');
      await page.screenshot({ path: `${SCREENSHOT_DIR}/${safeName}-terms.png` });
      await page.evaluate(() => {
        const scrollable = document.querySelector('[class*="scroll"]') || document.documentElement;
        scrollable.scrollTop = scrollable.scrollHeight;
      });
      await page.waitForTimeout(1000);

      const checkboxLabel = await page.$('label:has-text("I have read and accept")');
      if (checkboxLabel) {
        await checkboxLabel.click({ force: true });
        await page.waitForTimeout(500);
      }

      const acceptBtn = await page.$('button:has-text("Accept"), button:has-text("Continue"), button[type="submit"]');
      if (acceptBtn) {
        const btnDisabled = await acceptBtn.isDisabled();
        if (!btnDisabled) {
          await acceptBtn.click();
          await page.waitForTimeout(5000);
        }
      } else {
        // API fallback
        const accepted = await page.evaluate(async (creds) => {
          const loginResp = await fetch('/api/access-tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ emailOrUsername: creds.user, password: creds.pass }),
          });
          const loginData = await loginResp.json();
          if (loginData.item) return 'already-accepted';
          if (!loginData.pendingToken) return 'no-pending-token';
          const termsResp = await fetch('/api/terms', {
            headers: { Authorization: `Bearer ${loginData.pendingToken}` },
          });
          const termsData = await termsResp.json();
          const signature = termsData.item?.signature;
          if (!signature) return 'no-signature';
          const acceptResp = await fetch('/api/access-tokens/accept-terms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pendingToken: loginData.pendingToken, signature }),
          });
          const acceptData = await acceptResp.json();
          return acceptData.item ? 'accepted' : `failed: ${JSON.stringify(acceptData)}`;
        }, { user: ADMIN_USER, pass: ADMIN_PASS });

        await page.goto(`${urlBase}/`, { waitUntil: 'networkidle', timeout: 20000 });
        await page.waitForTimeout(2000);
        await page.fill('input[name="emailOrUsername"]', ADMIN_USER);
        await page.fill('input[name="password"]', ADMIN_PASS);
        await page.press('input[name="password"]', 'Enter');
        await page.waitForTimeout(5000);
      }
      url = page.url();
    }

    const safeName = label.replace(/[^a-z0-9-]/gi, '_');
    await page.screenshot({ path: `${SCREENSHOT_DIR}/${safeName}-final.png` });

    if (url.includes('login') || url.includes('terms')) {
      record('planka', `browser-login-${label}`, 'fail', `still on ${url}`, Date.now() - t0);
    } else {
      const wsErrors = errors.filter(e => e.includes('WebSocket') || e.includes('socket.io'));
      if (wsErrors.length > 0) {
        record('planka', `browser-login-${label}`, 'fail', `WebSocket errors: ${wsErrors[0].slice(0, 100)}`, Date.now() - t0);
      } else {
        record('planka', `browser-login-${label}`, 'pass', `logged in, URL: ${url}`, Date.now() - t0);
      }
    }
  } catch (err) {
    record('planka', `browser-login-${label}`, 'fail', err.message.split('\n')[0], Date.now() - t0);
  } finally {
    await context.close();
  }
}

// ── 6. Ollama ────────────────────────────────────────────────────────────────

async function testOllama() {
  console.log('\n── Ollama ──');

  const ollamaAuth = { user: ADMIN_USER, pass: ADMIN_PASS };

  // Health: tags
  await runTest('ollama', 'api-tags', async () => {
    const t0 = Date.now();
    const resp = await httpGet(`${BASE}/ollama/api/tags`, { auth: ollamaAuth });
    const text = await resp.text();
    if (text.includes('models')) {
      record('ollama', 'api-tags', 'pass', 'models endpoint responsive', Date.now() - t0);
    } else {
      record('ollama', 'api-tags', 'fail', text.slice(0, 80), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Health: version
  await runTest('ollama', 'api-version', async () => {
    const t0 = Date.now();
    const resp = await httpGet(`${BASE}/ollama/api/version`, { auth: ollamaAuth });
    const data = await resp.json();
    if (data.version) {
      record('ollama', 'api-version', 'pass', `version=${data.version}`, Date.now() - t0);
    } else {
      record('ollama', 'api-version', 'fail', JSON.stringify(data).slice(0, 80), Date.now() - t0);
    }
  }, { fullOnly: true });

  // Opt-in: generate
  if (TEST_OLLAMA) {
    await runTest('ollama', 'api-generate', async () => {
      const t0 = Date.now();
      const resp = await httpPost(`${BASE}/ollama/api/generate`, {
        model: 'any',
        prompt: 'Say hello in one word.',
        stream: false,
      }, { auth: ollamaAuth });
      const data = await resp.json();
      if (data.response && data.model) {
        record('ollama', 'api-generate', 'pass', `model=${data.model}`, Date.now() - t0);
      } else {
        record('ollama', 'api-generate', 'fail', JSON.stringify(data).slice(0, 120), Date.now() - t0);
      }
    }, { fullOnly: true });
  } else if (!MINIMAL) {
    skip('ollama', 'api-generate', 'requires --test-ollama');
  }
}

// ── 7. N.eko + CDP ──────────────────────────────────────────────────────────

async function testNeko(browser) {
  console.log('\n── N.eko + CDP ──');

  // Restart neko before testing — it can get stuck after a previous client disconnects.
  containerExec('supervisorctl restart neko', { timeout: 15000 });
  // Wait for neko to come back up and be ready to accept connections.
  for (let i = 0; i < 10; i++) {
    try {
      containerExec('curl -sf -o /dev/null http://127.0.0.1:8080/', { timeout: 5000 });
      break;
    } catch {
      if (i < 9) await new Promise(r => setTimeout(r, 2000));
    }
  }

  // Set up SSH tunnel once for all neko WebRTC tests.
  // Neko's WebRTC requires direct access to HTTP (8080) and TCPMUX (8081) ports.
  const sshKeyPath = '/tmp/e2e-ssh-key';
  try {
    execFileSync('test', ['-f', sshKeyPath], { stdio: 'pipe' });
  } catch {
    execFileSync('ssh-keygen', ['-t', 'ed25519', '-f', sshKeyPath, '-N', '', '-q'], { stdio: 'pipe' });
  }
  const pubKey = readFileSync(sshKeyPath + '.pub', 'utf8').trim();
  containerExec(`mkdir -p /workspace/data/coding/.ssh && grep -qF '${pubKey.split(' ')[1]}' /workspace/data/coding/.ssh/authorized_keys 2>/dev/null || echo '${pubKey}' >> /workspace/data/coding/.ssh/authorized_keys && chmod 700 /workspace/data/coding/.ssh && chmod 600 /workspace/data/coding/.ssh/authorized_keys && chown -R dev:dev /workspace/data/coding/.ssh`);

  try { execFileSync('pkill', ['-f', 'ssh.*18080.*127.0.0.1'], { stdio: 'pipe' }); } catch {}
  execFileSync('ssh', [
    '-i', sshKeyPath, '-o', 'IdentitiesOnly=yes',
    '-L', '127.0.0.1:18080:127.0.0.1:8080',
    '-p', '2222', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
    'dev@127.0.0.1', '-N', '-f',
  ], { stdio: 'pipe', timeout: 10000 });

  // Shared neko WebRTC context: stays open across login, CDP navigate, and screenshot tests
  let nekoContext = null;
  let nekoPage = null;
  let wsOpened = false;
  let loggedIn = false;

  try {
    // Test 1: WebRTC login
    await runTest('neko', 'webrtc-login', async () => {
      const t0 = Date.now();
      nekoContext = await browser.newContext();
      nekoPage = await nekoContext.newPage();
      nekoPage.setViewportSize({ width: 1280, height: 800 });
      nekoPage.on('websocket', () => { wsOpened = true; });

      await nekoPage.goto('http://127.0.0.1:18080/', { waitUntil: 'networkidle', timeout: 20000 });
      await nekoPage.waitForTimeout(2000);

      await nekoPage.fill('input[placeholder="Enter your display name"]', 'e2etest');
      await nekoPage.fill('input[placeholder="Password"]', ADMIN_PASS);
      await nekoPage.click('button:has-text("CONNECT")');

      for (let i = 0; i < 10; i++) {
        await nekoPage.waitForTimeout(3000);
        const hasLogin = await nekoPage.$('input[placeholder="Password"]');
        if (!hasLogin) { loggedIn = true; break; }
      }

      await nekoPage.screenshot({ path: `${SCREENSHOT_DIR}/neko-1-login.png` }).catch(() => {});

      if (loggedIn && wsOpened) {
        const hasVideo = !!(await nekoPage.$('video'));
        record('neko', 'webrtc-login', 'pass', `connected, ws=${wsOpened}, video=${hasVideo}`, Date.now() - t0);
      } else {
        record('neko', 'webrtc-login', 'fail', `loggedIn=${loggedIn}, ws=${wsOpened}`, Date.now() - t0);
      }
    });

    // Test 2: Navigate neko's browser via CDP to a recognizable page, then screenshot through WebRTC
    await runTest('neko', 'webrtc-verify-cdp', async () => {
      if (!loggedIn) throw new Error('WebRTC not connected');
      const t0 = Date.now();

      // Take a baseline screenshot of the current neko stream
      await nekoPage.screenshot({ path: `${SCREENSHOT_DIR}/neko-2-before.png` }).catch(() => {});

      // Open a new tab to Planka via CDP, then activate it
      const tabOut = containerExec('curl -sf -X PUT "http://127.0.0.1:9222/json/new?http://127.0.0.1:1337/"', { timeout: 10000 });
      const tabData = JSON.parse(tabOut);
      containerExec(`curl -sf http://127.0.0.1:9222/json/activate/${tabData.id}`, { timeout: 5000 });

      // Wait for the page to load and stream to update
      await nekoPage.waitForTimeout(5000);

      // Verify the tab loaded the expected URL
      const listOut = containerExec('curl -sf http://127.0.0.1:9222/json/list', { timeout: 5000 });
      const tabs = JSON.parse(listOut);
      const plankaTab = tabs.find(t => t.id === tabData.id);
      const tabUrl = plankaTab ? plankaTab.url : 'not found';
      const tabLoaded = tabUrl.includes('1337');

      await nekoPage.screenshot({ path: `${SCREENSHOT_DIR}/neko-3-after-cdp.png` }).catch(() => {});

      // Clean up the test tab
      try { containerExec(`curl -sf http://127.0.0.1:9222/json/close/${tabData.id}`, { timeout: 5000 }); } catch {}

      // Verify: WebRTC still connected and CDP tab loaded Planka
      const hasVideo = !!(await nekoPage.$('video'));
      if (hasVideo && wsOpened && tabLoaded) {
        record('neko', 'webrtc-verify-cdp', 'pass', `stream active, tab loaded ${tabUrl}`, Date.now() - t0);
      } else {
        record('neko', 'webrtc-verify-cdp', 'fail', `video=${hasVideo}, ws=${wsOpened}, tab=${tabUrl}`, Date.now() - t0);
      }
    });
  } finally {
    if (nekoContext) await nekoContext.close().catch(() => {});
  }

  // CDP: connect and get version
  await runTest('neko', 'cdp-version', async () => {
    const t0 = Date.now();
    const out = containerExec('curl -sf http://127.0.0.1:9222/json/version', { timeout: 10000 });
    const data = JSON.parse(out);
    if (data.Browser) {
      record('neko', 'cdp-version', 'pass', `browser=${data.Browser}`, Date.now() - t0);
    } else {
      record('neko', 'cdp-version', 'fail', 'no Browser field', Date.now() - t0);
    }
  });

  // CDP: list tabs, open new tab, verify, close
  let newTabId = '';
  await runTest('neko', 'cdp-open-tab', async () => {
    const t0 = Date.now();
    const out = containerExec('curl -sf -X PUT http://127.0.0.1:9222/json/new?about:blank', { timeout: 10000 });
    const data = JSON.parse(out);
    if (data.id) {
      newTabId = data.id;
      record('neko', 'cdp-open-tab', 'pass', `tab_id=${newTabId}`, Date.now() - t0);
    } else {
      record('neko', 'cdp-open-tab', 'fail', 'no tab id', Date.now() - t0);
    }
  });

  await runTest('neko', 'cdp-list-tabs', async () => {
    if (!newTabId) throw new Error('no tab to find');
    const t0 = Date.now();
    const out = containerExec('curl -sf http://127.0.0.1:9222/json/list', { timeout: 10000 });
    const tabs = JSON.parse(out);
    const found = tabs.some(t => t.id === newTabId);
    if (found) {
      record('neko', 'cdp-list-tabs', 'pass', `${tabs.length} tabs, new tab found`, Date.now() - t0);
    } else {
      record('neko', 'cdp-list-tabs', 'fail', `new tab not in ${tabs.length} tabs`, Date.now() - t0);
    }
  });

  await runTest('neko', 'cdp-close-tab', async () => {
    if (!newTabId) throw new Error('no tab to close');
    const t0 = Date.now();
    containerExec(`curl -sf http://127.0.0.1:9222/json/close/${newTabId}`, { timeout: 10000 });
    record('neko', 'cdp-close-tab', 'pass', 'tab closed', Date.now() - t0);
  });

  await runTest('neko', 'cdp-verify-closed', async () => {
    if (!newTabId) throw new Error('no tab to verify');
    const t0 = Date.now();
    const out = containerExec('curl -sf http://127.0.0.1:9222/json/list', { timeout: 10000 });
    const tabs = JSON.parse(out);
    const found = tabs.some(t => t.id === newTabId);
    if (!found) {
      record('neko', 'cdp-verify-closed', 'pass', 'tab no longer listed', Date.now() - t0);
    } else {
      record('neko', 'cdp-verify-closed', 'fail', 'tab still listed', Date.now() - t0);
    }
  });

  // Clean up SSH tunnel
  try { execFileSync('pkill', ['-f', 'ssh.*18080.*127.0.0.1'], { stdio: 'pipe' }); } catch {}
}

// ── 8. Terminal / ttyd ──────────────────────────────────────────────────────

async function testTerminal(browser) {
  console.log('\n── Terminal / ttyd ──');

  // Load terminal UI (existing)
  await runTest('terminal', 'load-ui', async () => {
    const t0 = Date.now();
    const context = await browser.newContext({
      httpCredentials: { username: ADMIN_USER, password: ADMIN_PASS },
    });
    const page = await context.newPage();
    try {
      await page.goto(`${BASE}/terminal/`, { waitUntil: 'domcontentloaded', timeout: 20000 });
      await page.waitForTimeout(3000);
      const html = await page.evaluate(() => document.body?.innerHTML?.length || 0);
      if (html > 100) {
        record('terminal', 'load-ui', 'pass', `htmlLength=${html}`, Date.now() - t0);
      } else {
        record('terminal', 'load-ui', 'fail', `htmlLength=${html}`, Date.now() - t0);
      }
    } finally {
      await page.screenshot({ path: `${SCREENSHOT_DIR}/terminal.png` }).catch(() => {});
      await context.close();
    }
  });

  // Write + read via exec
  const marker = `e2e-${randomUUID().slice(0, 8)}`;
  await runTest('terminal', 'exec-write', async () => {
    const t0 = Date.now();
    containerExec(`echo "${marker}" > /tmp/e2e-terminal-test`);
    record('terminal', 'exec-write', 'pass', `wrote marker ${marker}`, Date.now() - t0);
  });

  await runTest('terminal', 'exec-read', async () => {
    const t0 = Date.now();
    const out = containerExec('cat /tmp/e2e-terminal-test');
    if (out.includes(marker)) {
      record('terminal', 'exec-read', 'pass', 'marker verified', Date.now() - t0);
    } else {
      record('terminal', 'exec-read', 'fail', `expected "${marker}", got "${out}"`, Date.now() - t0);
    }
  });
}

// ── 9. Pushgateway / Prometheus ─────────────────────────────────────────────

async function testPushgateway() {
  console.log('\n── Pushgateway ──');

  const pgAuth = { user: ADMIN_USER, pass: ADMIN_PASS };

  // API write: push a metric
  await runTest('pushgateway', 'api-push-metric', async () => {
    const t0 = Date.now();
    const body = '# TYPE e2e_test_metric gauge\ne2e_test_metric 42\n';
    const resp = await httpPostText(
      `${BASE}/pushgateway/metrics/job/e2e-test/instance/test`,
      body,
      { auth: pgAuth },
    );
    if (resp.ok) {
      record('pushgateway', 'api-push-metric', 'pass', `HTTP ${resp.status}`, Date.now() - t0);
    } else {
      record('pushgateway', 'api-push-metric', 'fail', `HTTP ${resp.status}`, Date.now() - t0);
    }
  }, { fullOnly: true });

  // API read: verify metric
  await runTest('pushgateway', 'api-read-metric', async () => {
    const t0 = Date.now();
    const resp = await httpGet(`${BASE}/pushgateway/api/v1/metrics`, { auth: pgAuth });
    const data = await resp.json();
    const text = JSON.stringify(data);
    if (text.includes('e2e_test_metric') || text.includes('e2e-test')) {
      record('pushgateway', 'api-read-metric', 'pass', 'metric found', Date.now() - t0);
    } else {
      record('pushgateway', 'api-read-metric', 'fail', 'metric not found in response', Date.now() - t0);
    }
  }, { fullOnly: true });

  // Skill write: push via prometheus.sh
  await runTest('pushgateway', 'skill-push', async () => {
    const t0 = Date.now();
    const out = skillExec('/opt/conclave/pi/skills/prometheus', [
      'bash', 'prometheus.sh', 'push', '--metric', 'e2e_skill_gauge', '--value', '99',
    ]);
    record('pushgateway', 'skill-push', 'pass', out.slice(0, 80) || 'metric pushed via skill', Date.now() - t0);
  }, { fullOnly: true });

  // Skill read: verify via API
  await runTest('pushgateway', 'skill-verify', async () => {
    const t0 = Date.now();
    const resp = await httpGet(`${BASE}/pushgateway/api/v1/metrics`, { auth: pgAuth });
    const text = await resp.text();
    if (text.includes('e2e_skill_gauge')) {
      record('pushgateway', 'skill-verify', 'pass', 'skill gauge found', Date.now() - t0);
    } else {
      record('pushgateway', 'skill-verify', 'fail', 'skill gauge not found', Date.now() - t0);
    }
  }, { fullOnly: true });

  // Cleanup
  await runTest('pushgateway', 'api-cleanup', async () => {
    const t0 = Date.now();
    const resp = await httpDelete(
      `${BASE}/pushgateway/metrics/job/e2e-test/instance/test`,
      { auth: pgAuth },
    );
    // Also clean up skill-pushed metric
    await httpDelete(
      `${BASE}/pushgateway/metrics/job/agent`,
      { auth: pgAuth },
    ).catch(() => {});
    record('pushgateway', 'api-cleanup', 'pass', `HTTP ${resp.status}`, Date.now() - t0);
  }, { fullOnly: true });
}

// ── 10. SSH ──────────────────────────────────────────────────────────────────

async function testSSH() {
  console.log('\n── SSH ──');

  await runTest('ssh', 'tcp-connect', async () => {
    const t0 = Date.now();
    await tcpCheck('localhost', 2222);
    record('ssh', 'tcp-connect', 'pass', 'port 2222 open', Date.now() - t0);
  });
}

// ── 11. Healthcheck ─────────────────────────────────────────────────────────

async function testHealthcheck() {
  console.log('\n── Healthcheck ──');

  await runTest('healthcheck', 'agent-healthcheck', async () => {
    const t0 = Date.now();
    const out = containerExec('bash /opt/conclave/scripts/agent-healthcheck.sh --json', { timeout: 30000 });
    let data;
    try {
      data = JSON.parse(out);
    } catch {
      record('healthcheck', 'agent-healthcheck', 'fail', `invalid JSON: ${out.slice(0, 120)}`, Date.now() - t0);
      return;
    }
    // max_severity: 0=ok, 1=warning, 2=critical
    if (data.max_severity <= 1) {
      const sevLabel = data.max_severity === 0 ? 'ok' : 'warning';
      record('healthcheck', 'agent-healthcheck', 'pass', `severity=${sevLabel}`, Date.now() - t0);
    } else {
      const unhealthy = Object.entries(data.checks || {})
        .filter(([, v]) => v.status !== 'ok' && v.status !== 'warning')
        .map(([k]) => k);
      record('healthcheck', 'agent-healthcheck', 'fail', `unhealthy: ${unhealthy.join(', ')}`, Date.now() - t0);
    }
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════════════════════════════════════

(async () => {
  console.log(`=== Conclave E2E Tests (${MODE}) ===\n`);

  // Connect to browser
  let browser;
  let usedCDP = false;
  if (process.env.CDP_URL) {
    try {
      browser = await chromium.connectOverCDP(process.env.CDP_URL);
      usedCDP = true;
      console.log(`Connected via CDP (${process.env.CDP_URL})`);
    } catch (err) {
      console.error(`Failed to connect to CDP at ${process.env.CDP_URL}: ${err.message}`);
      process.exit(1);
    }
  } else {
    try {
      browser = await chromium.launch({ headless: true });
      console.log('Using local Playwright Chromium');
    } catch (err) {
      console.error('No local Chromium available. Run: npx playwright install chromium');
      console.error(`Detail: ${err.message.split('\n')[0]}`);
      process.exit(1);
    }
  }

  // Phase 1: Connectivity
  console.log('\n━━━ Phase 1: Connectivity ━━━');
  await testDashboard(browser);
  await testNginx();

  // Phase 2: Integration
  console.log('\n━━━ Phase 2: Integration ━━━');
  await testMatrix(browser);
  await testChromaDB();
  await testPlanka(browser);
  await testOllama();
  await testNeko(browser);
  await testTerminal(browser);
  await testPushgateway();
  await testSSH();
  await testHealthcheck();

  // Close browser
  if (usedCDP) {
    browser.close();
  } else {
    await browser.close();
  }

  // Summary
  const passed = results.filter(r => r.status === 'pass').length;
  const failed = results.filter(r => r.status === 'fail').length;
  const skipped = results.filter(r => r.status === 'skip').length;
  const total = results.length;

  console.log('\n=== SUMMARY ===');
  console.log(`${passed} passed, ${failed} failed, ${skipped} skipped out of ${total} tests`);

  if (failed > 0) {
    console.log('\nFailed:');
    results.filter(r => r.status === 'fail').forEach(r =>
      console.log(`  - ${r.group}/${r.name}: ${r.detail}`)
    );
  }

  // JSON output
  if (JSON_OUTPUT) {
    const output = {
      timestamp: new Date().toISOString(),
      mode: MODE,
      summary: { passed, failed, skipped, total },
      tests: results,
    };
    const jsonPath = '/tmp/conclave-test-results.json';
    writeFileSync(jsonPath, JSON.stringify(output, null, 2));
    console.log(`\nJSON results written to ${jsonPath}`);
  }

  process.exit(failed > 0 ? 1 : 0);
})();
