/**
 * Heartbeat Extension — Periodic Awareness
 *
 * Every N minutes, check for new messages, infrastructure health,
 * engagement events, and calendar items. Three tiers:
 *
 *   PULSE  (every beat, ~15m)  — Matrix messages, infrastructure pings.
 *   BREATH (every 3rd beat)    — Engagement, metrics, calendar.
 *   TIDE   (every 6th beat)    — Session refresh, deep metrics.
 *
 * When something urgent happens — a priority user sends a message,
 * a critical service goes down — the briefing is injected into
 * agent context for immediate action.
 *
 * Commands:
 *   /heartbeat           — Show status
 *   /heartbeat on        — Start periodic awareness
 *   /heartbeat off       — Stop
 *   /heartbeat run       — Run a check now
 *   /heartbeat history   — Show recent results
 *   /heartbeat briefing  — Show the last briefing in full
 *
 * Settings in .pi/settings.json:
 *   "heartbeat": {
 *     "autostart": true,
 *     "intervalMinutes": 15,
 *     "activeHours": { "start": "06:00", "end": "02:00" },
 *     "alertRoom": "",
 *     "alertOnMatrix": true,
 *     "injectUrgent": true,
 *     "prioritySenders": ["@admin:your-server.com"]
 *   }
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { type HeartbeatResult, runHeartbeat } from "./checks.js";

// ── Settings ────────────────────────────────────────────────

interface HeartbeatSettings {
	autostart: boolean;
	intervalMinutes: number;
	activeHours: { start: string; end: string } | null;
	alertRoom: string;
	alertOnMatrix: boolean;
	/** Inject urgent briefings into agent context */
	injectUrgent: boolean;
	/** Matrix user IDs whose messages trigger urgent alerts */
	prioritySenders: string[];
}

const DEFAULTS: HeartbeatSettings = {
	autostart: false,
	intervalMinutes: 15,
	activeHours: { start: "06:00", end: "02:00" },
	alertRoom: "",
	alertOnMatrix: true,
	injectUrgent: true,
	prioritySenders: [],
};

function resolveSettings(projectSettings: Record<string, any>): HeartbeatSettings {
	const cfg = projectSettings?.heartbeat ?? {};
	return {
		autostart: cfg.autostart ?? DEFAULTS.autostart,
		intervalMinutes: cfg.intervalMinutes ?? DEFAULTS.intervalMinutes,
		activeHours: cfg.activeHours !== undefined ? cfg.activeHours : DEFAULTS.activeHours,
		alertRoom: cfg.alertRoom ?? DEFAULTS.alertRoom,
		alertOnMatrix: cfg.alertOnMatrix ?? DEFAULTS.alertOnMatrix,
		injectUrgent: cfg.injectUrgent ?? DEFAULTS.injectUrgent,
		prioritySenders: cfg.prioritySenders ?? DEFAULTS.prioritySenders,
	};
}

// ── History ─────────────────────────────────────────────────

const MAX_HISTORY = 100;
const history: HeartbeatResult[] = [];

function pushHistory(result: HeartbeatResult): void {
	history.unshift(result);
	if (history.length > MAX_HISTORY) history.pop();
}

// ── Matrix Alert ────────────────────────────────────────────

async function sendMatrixAlert(pi: ExtensionAPI, roomId: string, message: string): Promise<void> {
	const homeserver = process.env.MATRIX_HOMESERVER_URL;
	const token = process.env.MATRIX_ACCESS_TOKEN;
	if (!homeserver || !token) return;

	try {
		const txnId = `${Date.now()}_hb_${Math.random().toString(36).slice(2, 8)}`;
		const body = JSON.stringify({ msgtype: "m.notice", body: message });
		await pi.exec("bash", ["-c",
			`curl -sf -X PUT ` +
			`-H "Content-Type: application/json" ` +
			`-H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" ` +
			`--data-raw '${body.replace(/'/g, "'\\''")}' ` +
			`"${homeserver}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${txnId}" ` +
			`2>/dev/null`
		]);
	} catch {
		// If Matrix itself is down, we can't alert via Matrix
	}
}

// ── Format Helpers ──────────────────────────────────────────

function formatDuration(ms: number): string {
	if (ms < 1000) return `${ms}ms`;
	return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(date: Date): string {
	return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function inActiveHours(settings: HeartbeatSettings): boolean {
	if (!settings.activeHours) return true;
	const { start, end } = settings.activeHours;
	const now = new Date();
	const currentMinutes = now.getHours() * 60 + now.getMinutes();

	const [startH, startM] = start.split(":").map(Number);
	const [endH, endM] = end.split(":").map(Number);
	const startMinutes = startH * 60 + startM;
	const endMinutes = endH * 60 + endM;

	if (endMinutes < startMinutes) {
		return currentMinutes >= startMinutes || currentMinutes < endMinutes;
	}
	return currentMinutes >= startMinutes && currentMinutes < endMinutes;
}

// ── Runner ──────────────────────────────────────────────────

class HeartbeatRunner {
	private pi: ExtensionAPI;
	private settings: HeartbeatSettings;
	private timer: ReturnType<typeof setInterval> | null = null;
	private running = false;
	private beatNumber = 0;
	private runCount = 0;
	private okCount = 0;
	private alertCount = 0;
	private lastRun: Date | null = null;
	private lastResult: HeartbeatResult | null = null;
	/** Callback for injecting urgent briefings into agent context */
	private onUrgent: ((briefing: string) => void) | null = null;
	/** UI context for status updates */
	private ctx: ExtensionContext | null = null;

	constructor(pi: ExtensionAPI, settings: HeartbeatSettings) {
		this.pi = pi;
		this.settings = settings;
	}

	setContext(ctx: ExtensionContext): void {
		this.ctx = ctx;
	}

	setOnUrgent(cb: (briefing: string) => void): void {
		this.onUrgent = cb;
	}

	start(): void {
		if (this.timer) return;
		const ms = this.settings.intervalMinutes * 60_000;
		this.timer = setInterval(() => this.tick(), ms);
	}

	stop(): void {
		if (this.timer) {
			clearInterval(this.timer);
			this.timer = null;
		}
	}

	isActive(): boolean {
		return this.timer !== null;
	}

	isRunning(): boolean {
		return this.running;
	}

	getStatus() {
		return {
			active: this.isActive(),
			running: this.running,
			beatNumber: this.beatNumber,
			runCount: this.runCount,
			okCount: this.okCount,
			alertCount: this.alertCount,
			lastRun: this.lastRun,
			lastResult: this.lastResult,
			intervalMinutes: this.settings.intervalMinutes,
		};
	}

	updateSettings(settings: HeartbeatSettings): void {
		const wasActive = this.isActive();
		const intervalChanged = this.settings.intervalMinutes !== settings.intervalMinutes;
		this.settings = settings;
		if (wasActive && intervalChanged) {
			this.stop();
			this.start();
		}
	}

	async runNow(): Promise<HeartbeatResult> {
		return this.execute();
	}

	private async tick(): Promise<void> {
		if (this.running) return;
		if (!inActiveHours(this.settings)) return;
		await this.execute();
	}

	private async execute(): Promise<HeartbeatResult> {
		this.running = true;
		this.beatNumber++;

		const sinceMinutes = this.lastRun
			? Math.ceil((Date.now() - this.lastRun.getTime()) / 60_000) + 1
			: this.settings.intervalMinutes + 1;

		// Emit start event for logger
		this.pi.events.emit("heartbeat:check", {
			beatNumber: this.beatNumber,
			sinceMinutes,
		});

		try {
			const result = await runHeartbeat(this.pi, this.beatNumber, sinceMinutes, this.settings.prioritySenders);

			this.lastRun = new Date();
			this.lastResult = result;
			this.runCount++;
			if (result.ok) this.okCount++;
			else this.alertCount++;

			pushHistory(result);

			// Emit result event for logger
			this.pi.events.emit("heartbeat:result", {
				beatNumber: result.beatNumber,
				tier: result.tier,
				ok: result.ok,
				urgent: result.urgent,
				durationMs: result.totalDurationMs,
				failedChecks: result.failedChecks,
			});

			// Update status bar
			if (this.ctx?.hasUI) {
				this.updateStatusBar(result);
			}

			// Handle urgency
			if (result.urgent) {
				// Alert via Matrix if configured
				if (this.settings.alertOnMatrix) {
					await sendMatrixAlert(this.pi, this.settings.alertRoom,
						`🫀 Heartbeat #${result.beatNumber} [${result.tier}] — Issues detected\n\n${result.briefing}`
					);
				}

				// Inject into agent context if configured
				if (this.settings.injectUrgent && this.onUrgent) {
					this.onUrgent(result.briefing);
				}

				// Also show as notification for visibility
				if (this.ctx?.hasUI) {
					this.ctx.ui.notify(result.briefing, "warning");
				}
			}

			return result;
		} catch (err: any) {
			const errorResult: HeartbeatResult = {
				beatNumber: this.beatNumber,
				tier: "pulse",
				ok: false,
				checks: [],
				totalDurationMs: 0,
				time: new Date().toISOString(),
				failedChecks: [`runner: ${err.message}`],
				briefing: `🫀 Heartbeat error: ${err.message}`,
				urgent: true,
			};

			this.lastRun = new Date();
			this.lastResult = errorResult;
			this.runCount++;
			this.alertCount++;
			pushHistory(errorResult);

			// Emit error event
			this.pi.events.emit("heartbeat:result", {
				beatNumber: this.beatNumber,
				tier: "pulse",
				ok: false,
				urgent: true,
				error: err.message,
			});

			return errorResult;
		} finally {
			this.running = false;
		}
	}

	private updateStatusBar(result: HeartbeatResult): void {
		if (!this.ctx?.hasUI) return;

		const th = this.ctx.ui.theme;
		const tierIcon = result.tier === "tide" ? "🌊" : result.tier === "breath" ? "🌬️" : "🫀";

		if (result.urgent) {
			const failSummary = result.failedChecks.length > 0
				? result.failedChecks.join(", ")
				: "urgent";

			// Check specifically for priority sender messages
			const matrixCheck = result.checks.find(c => c.name === "Matrix");
			const priorityCount = matrixCheck?.data?.priorityMessages?.length || 0;

			if (priorityCount > 0) {
				this.ctx.ui.setStatus("heartbeat",
					th.fg("warning", `${tierIcon} ${priorityCount} priority message${priorityCount > 1 ? "s" : ""} — check Matrix`)
				);
			} else {
				this.ctx.ui.setStatus("heartbeat",
					th.fg("error", `${tierIcon} ALERT: ${failSummary}`)
				);
			}
		} else {
			const okRate = this.runCount > 0 ? Math.round((this.okCount / this.runCount) * 100) : 100;
			this.ctx.ui.setStatus("heartbeat",
				th.fg("muted", `${tierIcon} #${result.beatNumber} OK (${okRate}% · ${formatDuration(result.totalDurationMs)})`)
			);
		}
	}
}

// ── Extension Entry ─────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	let runner: HeartbeatRunner | null = null;
	let settings: HeartbeatSettings = { ...DEFAULTS };
	let savedCtx: ExtensionContext | null = null;

	function getOrCreateRunner(): HeartbeatRunner {
		if (!runner) {
			runner = new HeartbeatRunner(pi, settings);
			if (savedCtx) runner.setContext(savedCtx);
		}
		return runner;
	}

	function startHeartbeat(): string {
		const r = getOrCreateRunner();
		if (r.isActive()) return "Heartbeat is already running.";
		r.start();
		return `✓ Heartbeat started (every ${settings.intervalMinutes}m — pulse/breath/tide)`;
	}

	function stopHeartbeat(): string {
		if (!runner?.isActive()) return "Heartbeat is not running.";
		runner.stop();
		return "✓ Heartbeat stopped.";
	}

	// ── Lifecycle ─────────────────────────────────────────────

	pi.on("session_start", async (_event, ctx) => {
		savedCtx = ctx;

		// Read settings from project settings
		try {
			const { stdout } = await pi.exec("bash", ["-c",
				`cat "${ctx.cwd}/.pi/settings.json" 2>/dev/null || echo "{}"`
			]);
			const parsed = JSON.parse(stdout.trim() || "{}");
			settings = resolveSettings(parsed);
		} catch {
			settings = { ...DEFAULTS };
		}

		if (settings.autostart) {
			runner = new HeartbeatRunner(pi, settings);
			runner.setContext(ctx);
			runner.start();
			wireUrgentCallback();

			if (ctx.hasUI) {
				ctx.ui.setStatus("heartbeat",
					ctx.ui.theme.fg("muted", "🫀 heartbeat active (awaiting first beat)")
				);
			}
		}
	});

	pi.on("session_shutdown", async () => {
		if (runner) {
			runner.stop();
			runner = null;
		}
		savedCtx = null;
	});

	// Wire up the urgent callback — actively trigger a turn when priority messages arrive.
	// The old approach used before_agent_start (passive — only fires when a turn is
	// already starting). This uses pi.sendMessage with triggerTurn to wake the agent.
	let lastUrgentInjection = 0;
	const URGENT_DEBOUNCE_MS = 60_000; // Don't re-inject urgents within 60s

	function wireUrgentCallback(): void {
		if (runner) {
			runner.setOnUrgent((briefing) => {
				const now = Date.now();
				if (now - lastUrgentInjection < URGENT_DEBOUNCE_MS) {
					// Debounce: too soon after last injection, skip
					return;
				}
				lastUrgentInjection = now;

				const message = {
					customType: "heartbeat-urgent",
					content: `[HEARTBEAT — Urgent]\n\n${briefing}\n\nCheck Matrix and address any priority messages before continuing other work.`,
					display: true,
				};

				if (savedCtx?.isIdle()) {
					// Agent is idle — trigger a new turn immediately
					pi.sendMessage(message, { triggerTurn: true });
				} else {
					// Agent is busy — queue as follow-up after current turn
					pi.sendMessage(message, { triggerTurn: true, deliverAs: "followUp" });
				}
			});
		}
	}

	// ── Message Renderer ──────────────────────────────────────

	pi.registerMessageRenderer("heartbeat-urgent", (message) => {
		// Return undefined to use default rendering — content is already
		// a well-formatted string. The display: true flag ensures it shows.
		return undefined;
	});

	// ── Command: /heartbeat ───────────────────────────────────

	pi.registerCommand("heartbeat", {
		description: "Awareness system — /heartbeat on | off | run | status | history | briefing",
		getArgumentCompletions: (prefix: string) => {
			const items = [
				{ value: "on", label: "on — Start periodic awareness" },
				{ value: "off", label: "off — Stop the heartbeat" },
				{ value: "run", label: "run — Run a check now" },
				{ value: "status", label: "status — Show heartbeat statistics" },
				{ value: "history", label: "history — Show recent results" },
				{ value: "briefing", label: "briefing — Show the last full briefing" },
			];
			return items.filter(i => i.value.startsWith(prefix));
		},
		handler: async (args, ctx) => {
			savedCtx = ctx;
			const arg = args?.trim().toLowerCase();

			// ── ON ────────────────────────────────────
			if (arg === "on" || arg === "start") {
				const result = startHeartbeat();
				wireUrgentCallback();
				ctx.ui.notify(result, result.startsWith("✓") ? "info" : "error");
				if (result.startsWith("✓")) {
					ctx.ui.setStatus("heartbeat",
						ctx.ui.theme.fg("muted", "🫀 heartbeat active (awaiting first beat)")
					);
				}
				return;
			}

			// ── OFF ───────────────────────────────────
			if (arg === "off" || arg === "stop") {
				const result = stopHeartbeat();
				ctx.ui.notify(result, result.startsWith("✓") ? "info" : "error");
				ctx.ui.setStatus("heartbeat", undefined);
				return;
			}

			// ── RUN NOW ───────────────────────────────
			if (arg === "run" || arg === "now") {
				ctx.ui.notify("🫀 Running check…", "info");

				const r = getOrCreateRunner();
				r.setContext(ctx);
				const result = await r.runNow();

				const lines: string[] = [];
				lines.push("═══════════════════════════════════════");
				lines.push(result.ok
					? "  💚 HEARTBEAT — All Clear"
					: "  🫀 HEARTBEAT — Issues Detected"
				);
				lines.push(`  Beat #${result.beatNumber} [${result.tier}] — ${formatDuration(result.totalDurationMs)}`);
				lines.push("═══════════════════════════════════════");
				lines.push("");

				// Show the briefing
				lines.push(result.briefing);

				lines.push("");
				lines.push("─── Check Details ───");
				for (const check of result.checks) {
					const icon = check.ok
						? ctx.ui.theme.fg("success", "✓")
						: ctx.ui.theme.fg("error", "✗");
					const name = ctx.ui.theme.fg("accent", check.name.padEnd(20));
					const duration = ctx.ui.theme.fg("dim", `(${formatDuration(check.durationMs)})`);
					lines.push(`  ${icon} ${name} ${check.message} ${duration}`);
				}

				ctx.ui.notify(lines.join("\n"), result.urgent ? "warning" : "info");
				return;
			}

			// ── HISTORY ───────────────────────────────
			if (arg === "history") {
				if (history.length === 0) {
					ctx.ui.notify("No heartbeat history yet. Use /heartbeat run to start.", "info");
					return;
				}

				const lines: string[] = [];
				lines.push("═══════════════════════════════════════");
				lines.push("  HEARTBEAT HISTORY");
				lines.push("═══════════════════════════════════════");
				lines.push("");

				const show = history.slice(0, 20);
				for (const entry of show) {
					const time = new Date(entry.time);
					const tierIcon = entry.tier === "tide" ? "🌊" : entry.tier === "breath" ? "🌬️" : "🫀";
					const okIcon = entry.ok ? "💚" : "⚠";
					const passed = entry.checks.filter(c => c.ok).length;
					const total = entry.checks.length;
					const duration = formatDuration(entry.totalDurationMs);

					let line = `  ${okIcon} ${tierIcon} #${entry.beatNumber} ${formatTime(time)} — ${passed}/${total} (${duration})`;
					if (entry.urgent) line += " ❗";
					if (!entry.ok) line += ` [${entry.failedChecks.join(", ")}]`;
					lines.push(line);
				}

				if (history.length > 20) {
					lines.push(`\n  … and ${history.length - 20} older entries`);
				}

				ctx.ui.notify(lines.join("\n"), "info");
				return;
			}

			// ── BRIEFING ──────────────────────────────
			if (arg === "briefing" || arg === "brief") {
				const last = runner?.getStatus().lastResult;
				if (!last) {
					ctx.ui.notify("No heartbeat has run yet. Use /heartbeat run first.", "info");
					return;
				}
				ctx.ui.notify(last.briefing, last.urgent ? "warning" : "info");
				return;
			}

			// ── STATUS (default) ──────────────────────
			{
				const s = runner?.getStatus();
				const lines: string[] = [];

				lines.push("═══════════════════════════════════════");
				lines.push("  HEARTBEAT — Awareness System");
				lines.push("═══════════════════════════════════════");
				lines.push("");

				if (!s || !s.active) {
					lines.push("  State: " + ctx.ui.theme.fg("muted", "Inactive"));
					lines.push("");
					lines.push("  Use /heartbeat on to start periodic awareness.");
					lines.push("  Use /heartbeat run for an immediate check.");
				} else {
					lines.push("  State: " + ctx.ui.theme.fg("success", "Active") +
						` (every ${s.intervalMinutes}m)`);
					lines.push("");
					lines.push("  ─── Statistics ───");
					lines.push(`  Beats: ${s.runCount} (current: #${s.beatNumber})`);
					lines.push(`  OK: ${s.okCount} · Alerts: ${s.alertCount}`);

					if (s.runCount > 0) {
						const okRate = Math.round((s.okCount / s.runCount) * 100);
						lines.push(`  Health: ${okRate}%`);
					}

					if (s.lastRun) {
						const ago = Math.round((Date.now() - s.lastRun.getTime()) / 60_000);
						lines.push(`  Last: ${formatTime(s.lastRun)} (${ago}m ago) — ${s.lastResult?.tier || "?"}`);
					} else {
						lines.push("  Last: No beats yet (first at next interval)");
					}

					lines.push("");
					lines.push("  ─── Tiers ───");
					lines.push("  🫀 Pulse   every beat     Matrix messages, infrastructure");
					lines.push("  🌬️ Breath  every 3rd beat  Engagement, metrics, calendar");
					lines.push("  🌊 Tide    every 6th beat  Session refresh, deep ingest");
				}

				lines.push("");
				lines.push("  ─── Configuration ───");
				lines.push(`  Interval: ${settings.intervalMinutes}m`);
				lines.push(`  Active Hours: ${settings.activeHours
					? `${settings.activeHours.start}–${settings.activeHours.end}`
					: "24/7"}`);
				lines.push(`  Matrix Alerts: ${settings.alertOnMatrix ? "enabled" : "disabled"}`);
				lines.push(`  Urgent Injection: ${settings.injectUrgent ? "enabled" : "disabled"}`);
				lines.push(`  History: ${history.length} entries`);

				ctx.ui.notify(lines.join("\n"), "info");
			}
		},
	});
}
