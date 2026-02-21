/**
 * Cron Extension — Scheduled Jobs
 *
 * Scheduled jobs that fire on cron expressions, each running as an
 * isolated pi subprocess. Edit the crontab file directly — the
 * scheduler watches for changes and reloads automatically.
 *
 * Commands:
 *   /cron            — Show status and job list
 *   /cron on         — Start the scheduler
 *   /cron off        — Stop the scheduler
 *   /cron run <name> — Trigger a job immediately
 *   /cron add <name> <schedule> <prompt>  — Add a new job
 *   /cron remove <name>  — Remove a job
 *   /cron enable <name>  — Enable a disabled job
 *   /cron disable <name> — Disable a job
 *
 * Settings in .pi/settings.json:
 *   "cron": {
 *     "autostart": false,
 *     "activeHours": { "start": "06:00", "end": "02:00" },
 *     "alertRoom": "",
 *     "showOk": false
 *   }
 *
 * Based on pi-cron by Espen Nilsen.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import {
	ensureTabFile, loadJobs, addJob, removeJob, updateJob, getJob,
	setTabPath, validateCron, type CronJob,
} from "./crontab.js";
import { CronScheduler, type CronSettings } from "./scheduler.js";

// ── Settings ────────────────────────────────────────────────────

const DEFAULTS: CronSettings = {
	autostart: false,
	activeHours: { start: "06:00", end: "02:00" },
	alertRoom: "",
	showOk: false,
};

function resolveSettings(projectSettings: Record<string, any>): CronSettings {
	const cfg = projectSettings?.cron ?? {};
	return {
		autostart: cfg.autostart ?? DEFAULTS.autostart,
		activeHours: cfg.activeHours !== undefined ? cfg.activeHours : DEFAULTS.activeHours,
		alertRoom: cfg.alertRoom ?? DEFAULTS.alertRoom,
		showOk: cfg.showOk ?? DEFAULTS.showOk,
	};
}

// ── Matrix Alert ────────────────────────────────────────────────

async function sendMatrixAlert(pi: ExtensionAPI, roomId: string, message: string): Promise<void> {
	const homeserver = process.env.MATRIX_HOMESERVER_URL;
	const token = process.env.MATRIX_ACCESS_TOKEN;
	if (!homeserver || !token) return;

	try {
		const txnId = `${Date.now()}_cron_${Math.random().toString(36).slice(2, 8)}`;
		const body = JSON.stringify({ msgtype: "m.notice", body: message });
		await pi.exec("bash", ["-c",
			`curl -sf -X PUT ` +
			`-H "Content-Type: application/json" ` +
			`-H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" ` +
			`--data-raw '${body.replace(/'/g, "'\\''")}' ` +
			`"${homeserver}/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${txnId}" ` +
			`2>/dev/null`
		]);
	} catch { /* Silent */ }
}

// ── Format Helpers ──────────────────────────────────────────────

function formatDuration(ms: number): string {
	if (ms < 1000) return `${ms}ms`;
	if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
	return `${(ms / 60_000).toFixed(1)}m`;
}

function formatJobLine(job: CronJob & { running?: boolean }, theme: any): string {
	const status = job.disabled
		? theme.fg("dim", "⏸ disabled")
		: job.running
			? theme.fg("warning", "🔄 running")
			: theme.fg("success", "✓ active");
	const channel = job.channel !== "general" ? theme.fg("dim", ` [${job.channel}]`) : "";
	const prompt = job.prompt.length > 60 ? job.prompt.slice(0, 60) + "…" : job.prompt;
	return `  ${status} ${theme.fg("accent", job.name)} ${theme.fg("dim", job.schedule)}${channel}\n    ${theme.fg("muted", prompt)}`;
}

// ── Extension Entry ─────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	let scheduler: CronScheduler | null = null;
	let settings: CronSettings = { ...DEFAULTS };
	let savedCtx: ExtensionContext | null = null;

	function createScheduler(): CronScheduler {
		return new CronScheduler(process.cwd(), settings, {
			onJobStart: (event) => {
				// Emit event for logger
				pi.events.emit("cron:job_start", {
					name: event.job.name,
					schedule: event.job.schedule,
				});

				if (savedCtx?.hasUI) {
					savedCtx.ui.setStatus("cron",
						savedCtx.ui.theme.fg("warning", `⏰ running "${event.job.name}"…`)
					);
				}
			},
			onJobComplete: (event) => {
				// Emit event for logger
				pi.events.emit("cron:job_complete", {
					name: event.job.name,
					ok: event.ok,
					durationMs: event.durationMs,
					error: event.error,
				});

				if (savedCtx?.hasUI) {
					const s = scheduler?.getStatus();
					savedCtx.ui.setStatus("cron",
						savedCtx.ui.theme.fg("muted",
							`⏰ cron active (${s?.enabledCount ?? "?"} jobs · ${s?.runCount ?? 0} runs)`
						)
					);
				}
			},
			onReload: (jobs) => {
				pi.events.emit("cron:reload", {
					jobCount: jobs.length,
					enabledCount: jobs.filter(j => !j.disabled).length,
				});
			},
			onAlert: (message) => {
				sendMatrixAlert(pi, settings.alertRoom, message);
			},
		});
	}

	function startScheduler(): string {
		if (scheduler?.isActive()) return "Scheduler is already running.";
		if (!scheduler) scheduler = createScheduler();
		scheduler.start();
		return `✓ Cron scheduler started (${scheduler.getStatus().enabledCount} active jobs)`;
	}

	function stopScheduler(): string {
		if (!scheduler?.isActive()) return "Scheduler is not running.";
		scheduler.stop();
		return "✓ Cron scheduler stopped.";
	}

	// ── Lifecycle ─────────────────────────────────────────────

	pi.on("session_start", async (_event, ctx) => {
		savedCtx = ctx;

		// Set crontab path relative to project
		setTabPath(`${ctx.cwd}/.pi/cron.tab`);
		ensureTabFile();

		// Read settings
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
			scheduler = createScheduler();
			scheduler.start();
			if (ctx.hasUI) {
				const s = scheduler.getStatus();
				ctx.ui.setStatus("cron",
					ctx.ui.theme.fg("muted", `⏰ cron active (${s.enabledCount} jobs)`)
				);
			}
		}
	});

	pi.on("session_shutdown", async () => {
		if (scheduler) {
			scheduler.stop();
			scheduler = null;
		}
		savedCtx = null;
	});

	// ── Command: /cron ────────────────────────────────────────

	pi.registerCommand("cron", {
		description: "Scheduled jobs — /cron on | off | run <name> | add | remove | enable | disable",
		getArgumentCompletions: (prefix: string) => {
			const items = [
				{ value: "on", label: "on — Start the cron scheduler" },
				{ value: "off", label: "off — Stop the scheduler" },
				{ value: "run", label: "run <name> — Trigger a job now" },
				{ value: "add", label: "add <name> <schedule> <prompt> — Add a job" },
				{ value: "remove", label: "remove <name> — Remove a job" },
				{ value: "enable", label: "enable <name> — Enable a job" },
				{ value: "disable", label: "disable <name> — Disable a job" },
			];
			return items.filter(i => i.value.startsWith(prefix));
		},
		handler: async (args, ctx) => {
			savedCtx = ctx;
			const parts = (args ?? "").trim().split(/\s+/);
			const cmd = parts[0]?.toLowerCase();

			// ── ON ────────────────────────────────────
			if (cmd === "on" || cmd === "start") {
				const result = startScheduler();
				ctx.ui.notify(result, result.startsWith("✓") ? "info" : "error");
				if (result.startsWith("✓")) {
					const s = scheduler!.getStatus();
					ctx.ui.setStatus("cron",
						ctx.ui.theme.fg("muted", `⏰ cron active (${s.enabledCount} jobs)`)
					);
				}
				return;
			}

			// ── OFF ───────────────────────────────────
			if (cmd === "off" || cmd === "stop") {
				const result = stopScheduler();
				ctx.ui.notify(result, result.startsWith("✓") ? "info" : "error");
				ctx.ui.setStatus("cron", undefined);
				return;
			}

			// ── RUN NOW ───────────────────────────────
			if (cmd === "run") {
				const name = parts[1];
				if (!name) {
					ctx.ui.notify("Usage: /cron run <job-name>", "error");
					return;
				}
				if (!scheduler) scheduler = createScheduler();
				const result = scheduler.runNow(name);
				ctx.ui.notify(result, result.startsWith("✓") ? "info" : "error");
				return;
			}

			// ── ADD ───────────────────────────────────
			if (cmd === "add") {
				// /cron add <name> <5-field-schedule> <prompt...>
				const name = parts[1];
				if (!name || parts.length < 8) {
					ctx.ui.notify(
						"Usage: /cron add <name> <min> <hour> <dom> <month> <dow> <prompt...>\n" +
						"Example: /cron add morning-brief 0 9 * * 1-5 Check Matrix and summarize the state of things",
						"error"
					);
					return;
				}
				const schedule = parts.slice(2, 7).join(" ");
				const prompt = parts.slice(7).join(" ");
				const err = validateCron(schedule);
				if (err) {
					ctx.ui.notify(`Invalid cron expression: ${err}`, "error");
					return;
				}
				const ok = addJob({ name, schedule, prompt, channel: "general", disabled: false });
				ctx.ui.notify(
					ok ? `✓ Added job "${name}" (${schedule})` : `Job "${name}" already exists.`,
					ok ? "info" : "error"
				);
				return;
			}

			// ── REMOVE ────────────────────────────────
			if (cmd === "remove" || cmd === "rm") {
				const name = parts[1];
				if (!name) { ctx.ui.notify("Usage: /cron remove <name>", "error"); return; }
				const ok = removeJob(name);
				ctx.ui.notify(
					ok ? `✓ Removed "${name}"` : `Job "${name}" not found.`,
					ok ? "info" : "error"
				);
				return;
			}

			// ── ENABLE ────────────────────────────────
			if (cmd === "enable") {
				const name = parts[1];
				if (!name) { ctx.ui.notify("Usage: /cron enable <name>", "error"); return; }
				const ok = updateJob(name, { disabled: false });
				ctx.ui.notify(
					ok ? `✓ Enabled "${name}"` : `Job "${name}" not found.`,
					ok ? "info" : "error"
				);
				return;
			}

			// ── DISABLE ───────────────────────────────
			if (cmd === "disable") {
				const name = parts[1];
				if (!name) { ctx.ui.notify("Usage: /cron disable <name>", "error"); return; }
				const ok = updateJob(name, { disabled: true });
				ctx.ui.notify(
					ok ? `✓ Disabled "${name}"` : `Job "${name}" not found.`,
					ok ? "info" : "error"
				);
				return;
			}

			// ── STATUS (default) ──────────────────────
			{
				const s = scheduler?.getStatus();
				const jobs = scheduler ? scheduler.list() : loadJobs().map(j => ({ ...j, running: false }));
				const lines: string[] = [];

				lines.push("═══════════════════════════════════════");
				lines.push("  CRON — Scheduled Jobs");
				lines.push("═══════════════════════════════════════");
				lines.push("");

				if (!s || !s.active) {
					lines.push("  Scheduler: " + ctx.ui.theme.fg("muted", "Inactive"));
					lines.push("  Use /cron on to start.");
				} else {
					lines.push("  Scheduler: " + ctx.ui.theme.fg("success", "Active"));
					lines.push(`  Jobs: ${s.enabledCount} active of ${s.jobCount} total`);
					lines.push(`  Runs: ${s.runCount} (${s.okCount} OK, ${s.errorCount} errors)`);
					if (s.runningNames.length > 0) {
						lines.push(`  Running: ${s.runningNames.join(", ")}`);
					}
				}

				lines.push("");
				lines.push(`  Active Hours: ${settings.activeHours
					? `${settings.activeHours.start}–${settings.activeHours.end}`
					: "24/7"}`);

				if (jobs.length > 0) {
					lines.push("");
					lines.push("  ─── Jobs ───");
					for (const job of jobs) {
						lines.push(formatJobLine(job, ctx.ui.theme));
					}
				} else {
					lines.push("");
					lines.push("  No jobs configured.");
					lines.push("  Edit .pi/cron.tab or use /cron add <name> <schedule> <prompt>");
				}

				ctx.ui.notify(lines.join("\n"), "info");
			}
		},
	});
}
