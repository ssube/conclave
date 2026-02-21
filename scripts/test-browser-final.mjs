#!/usr/bin/env node
// End-to-end browser tests for all Conclave services
// Tests the full flow including Planka terms acceptance in browser
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { execSync } from 'child_process';

const BASE = 'http://localhost:8888';
const SCREENSHOT_DIR = '/tmp/conclave-screenshots';
mkdirSync(SCREENSHOT_DIR, { recursive: true });

// Read admin password from env or from container secrets file
function getAdminPassword() {
  if (process.env.CONCLAVE_ADMIN_PASSWORD) return process.env.CONCLAVE_ADMIN_PASSWORD;
  try {
    const out = execSync(
      'docker exec conclave-dev grep CONCLAVE_ADMIN_PASSWORD /workspace/config/generated-secrets.env 2>/dev/null | cut -d= -f2',
      { encoding: 'utf8', timeout: 5000 }
    ).trim();
    if (out) return out;
  } catch {}
  return 'admin'; // fallback for legacy setups
}

const ADMIN_PASS = getAdminPassword();
const ADMIN_USER = 'admin';
const PLANKA_USER = 'admin';
const PLANKA_PASS = ADMIN_PASS;
const NEKO_PASS = ADMIN_PASS;

const results = [];
function log(service, status, detail = '') {
  const icon = status === 'OK' ? 'PASS' : 'FAIL';
  console.log(`[${icon}] ${service}: ${detail}`);
  results.push({ service, status, detail });
}

async function testPage(browser, name, url, { auth, check, timeout = 15000 } = {}) {
  const context = await browser.newContext(
    auth ? { httpCredentials: { username: auth.user, password: auth.pass } } : {}
  );
  const page = await context.newPage();
  page.setViewportSize({ width: 1280, height: 800 });
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout });
    const status = response?.status();
    if (status >= 400) {
      log(name, 'FAIL', `HTTP ${status}`);
      return;
    }
    if (check) {
      await check(page);
    } else {
      log(name, 'OK', `HTTP ${status}`);
    }
  } catch (err) {
    log(name, 'FAIL', err.message.split('\n')[0]);
  } finally {
    const safeName = name.replace(/[^a-z0-9-]/gi, '_');
    await page.screenshot({ path: `${SCREENSHOT_DIR}/${safeName}.png` }).catch(() => {});
    await context.close();
  }
}

// Full Planka login flow: login -> terms acceptance -> dashboard
async function testPlankaFullLogin(browser, urlBase, label) {
  console.log(`\n--- ${label} ---`);
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setViewportSize({ width: 1280, height: 800 });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

  try {
    await page.goto(`${urlBase}/`, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // Step 1: Login
    console.log('  Step 1: Filling login form...');
    await page.fill('input[name="emailOrUsername"]', PLANKA_USER);
    await page.fill('input[name="password"]', PLANKA_PASS);
    await page.press('input[name="password"]', 'Enter');
    await page.waitForTimeout(5000);

    let url = page.url();
    console.log(`  After login: ${url}`);

    // Step 2: Handle terms page if present
    const termsVisible = await page.$('text=End User Terms');
    if (termsVisible) {
      console.log('  Step 2: Terms page detected, accepting...');
      const safeName = label.replace(/[^a-z0-9-]/gi, '_');
      await page.screenshot({ path: `${SCREENSHOT_DIR}/${safeName}-terms.png` });

      // Scroll to bottom of terms
      await page.evaluate(() => {
        const scrollable = document.querySelector('[class*="scroll"]') || document.documentElement;
        scrollable.scrollTop = scrollable.scrollHeight;
      });
      await page.waitForTimeout(1000);

      // Click the label that contains the checkbox (label intercepts clicks)
      const checkboxLabel = await page.$('label:has-text("I have read and accept")');
      if (checkboxLabel) {
        await checkboxLabel.click({ force: true });
        await page.waitForTimeout(500);
      }

      // Find and click the accept/submit button
      const acceptBtn = await page.$('button:has-text("Accept"), button:has-text("Continue"), button[type="submit"]');
      if (acceptBtn) {
        const btnDisabled = await acceptBtn.isDisabled();
        console.log(`  Accept button disabled: ${btnDisabled}`);
        if (!btnDisabled) {
          await acceptBtn.click();
          await page.waitForTimeout(5000);
        }
      } else {
        console.log('  No accept button found, trying API fallback...');
        // API fallback for terms acceptance
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
            headers: { 'Authorization': `Bearer ${loginData.pendingToken}` },
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
        }, { user: PLANKA_USER, pass: PLANKA_PASS });
        console.log(`  API terms result: ${accepted}`);

        // Reload and re-login
        await page.goto(`${urlBase}/`, { waitUntil: 'networkidle', timeout: 20000 });
        await page.waitForTimeout(2000);
        await page.fill('input[name="emailOrUsername"]', PLANKA_USER);
        await page.fill('input[name="password"]', PLANKA_PASS);
        await page.press('input[name="password"]', 'Enter');
        await page.waitForTimeout(5000);
      }

      url = page.url();
      console.log(`  After terms: ${url}`);
    } else {
      console.log('  Step 2: No terms page (already accepted)');
    }

    // Step 3: Verify we're on the dashboard
    const safeName = label.replace(/[^a-z0-9-]/gi, '_');
    await page.screenshot({ path: `${SCREENSHOT_DIR}/${safeName}-final.png` });

    if (url.includes('login') || url.includes('terms')) {
      log(label, 'FAIL', `Still on ${url}`);
    } else {
      const wsErrors = errors.filter(e => e.includes('WebSocket') || e.includes('socket.io'));
      if (wsErrors.length > 0) {
        log(label, 'FAIL', `Logged in but WebSocket errors: ${wsErrors[0].substring(0, 100)}`);
      } else {
        log(label, 'OK', `Logged in, URL: ${url}`);
      }
    }
  } catch (err) {
    log(label, 'FAIL', err.message.split('\n')[0]);
  } finally {
    await context.close();
  }
}

(async () => {
  console.log('=== Conclave End-to-End Browser Tests ===\n');
  const browser = await chromium.launch({ headless: true });

  // --- 1. Dashboard ---
  await testPage(browser, 'Dashboard', `${BASE}/`, {
    auth: { user: ADMIN_USER, pass: ADMIN_PASS },
    check: async (page) => {
      const heading = await page.textContent('h1');
      log('Dashboard', 'OK', `h1="${heading}"`);
    }
  });

  // --- 2. Element Web ---
  await testPage(browser, 'Element Web', `${BASE}/element/`, {
    check: async (page) => {
      await page.waitForTimeout(3000);
      const title = await page.title();
      log('Element Web', title.includes('Element') ? 'OK' : 'FAIL', `title="${title}"`);
    },
    timeout: 20000
  });

  // --- 3. Matrix API ---
  await testPage(browser, 'Matrix API', `${BASE}/_matrix/client/versions`, {
    check: async (page) => {
      const text = await page.textContent('body');
      const data = JSON.parse(text);
      log('Matrix API', data.versions ? 'OK' : 'FAIL', `${data.versions?.length} versions`);
    }
  });

  // --- 4. ChromaDB API ---
  await testPage(browser, 'ChromaDB API', `${BASE}/chromadb/api/v2/heartbeat`, {
    check: async (page) => {
      const text = await page.textContent('body');
      log('ChromaDB API', text.includes('heartbeat') ? 'OK' : 'FAIL', text.trim().substring(0, 80));
    }
  });

  // --- 5. Ollama API ---
  await testPage(browser, 'Ollama API', `${BASE}/ollama/api/tags`, {
    auth: { user: ADMIN_USER, pass: ADMIN_PASS },
    check: async (page) => {
      const text = await page.textContent('body');
      log('Ollama API', text.includes('models') ? 'OK' : 'FAIL', 'models endpoint responsive');
    }
  });

  // --- 6. Terminal (ttyd) ---
  await testPage(browser, 'Terminal', `${BASE}/terminal/`, {
    auth: { user: ADMIN_USER, pass: ADMIN_PASS },
    check: async (page) => {
      await page.waitForTimeout(3000);
      const html = await page.evaluate(() => document.body?.innerHTML?.length || 0);
      log('Terminal', html > 100 ? 'OK' : 'FAIL', `htmlLength=${html}`);
    },
    timeout: 20000
  });

  // --- 7. Planka full login on localhost:1337 ---
  await testPlankaFullLogin(browser, 'http://localhost:1337', 'Planka-localhost-1337');

  // --- 8. Planka full login on 127.0.0.1:1337 ---
  await testPlankaFullLogin(browser, 'http://127.0.0.1:1337', 'Planka-127.0.0.1-1337');

  // --- 9. Neko login + WebRTC ---
  console.log('\n--- Neko WebRTC ---');
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setViewportSize({ width: 1280, height: 800 });
    const msgs = [];
    page.on('console', msg => msgs.push(`[${msg.type()}] ${msg.text()}`));

    try {
      await page.goto(`${BASE}/neko/`, { waitUntil: 'networkidle', timeout: 20000 });
      await page.waitForTimeout(2000);

      await page.fill('input[placeholder="Enter your display name"]', 'admin');
      await page.fill('input[placeholder="Password"]', NEKO_PASS);
      await page.click('button:has-text("CONNECT")');

      console.log('  Waiting 15s for WebRTC connection...');
      await page.waitForTimeout(15000);

      await page.screenshot({ path: `${SCREENSHOT_DIR}/Neko-WebRTC.png` });

      const hasLogin = await page.$('input[placeholder="Password"]');
      const nekoErrors = msgs.filter(m => m.includes('[error]') || m.includes('Error'));
      const connected = msgs.some(m => m.includes('connected'));

      if (hasLogin) {
        log('Neko WebRTC', 'FAIL', 'Still on login screen');
      } else if (connected) {
        log('Neko WebRTC', 'OK', 'Connected successfully');
      } else {
        log('Neko WebRTC', 'OK', `Past login, ${nekoErrors.length} errors in console`);
      }

      const relevant = msgs.filter(m =>
        m.includes('NEKO') || m.includes('webrtc') || m.includes('ice') ||
        m.includes('peer') || m.includes('connected') || m.includes('error')
      );
      if (relevant.length > 0) {
        console.log(`  Console (${relevant.length} relevant):`);
        relevant.slice(0, 10).forEach(m => console.log(`    ${m}`));
      }
    } catch (err) {
      log('Neko WebRTC', 'FAIL', err.message.split('\n')[0]);
    }
    await context.close();
  }

  await browser.close();

  // --- Summary ---
  console.log('\n=== SUMMARY ===');
  const passed = results.filter(r => r.status === 'OK').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  console.log(`${passed} passed, ${failed} failed out of ${results.length} tests`);

  if (failed > 0) {
    console.log('\nFailed:');
    results.filter(r => r.status === 'FAIL').forEach(r => console.log(`  - ${r.service}: ${r.detail}`));
  }

  process.exit(failed > 0 ? 1 : 0);
})();
