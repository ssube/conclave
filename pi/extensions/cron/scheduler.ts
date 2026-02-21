/**
 * Cron Scheduler
 *
 * Ticks every 30 seconds. When the minute matches a cron expression,
 * spawns an isolated `pi -p --no-session` subprocess to execute the job.
 *
 * Each job gets a fresh agent context — crash-isolated, no shared state.
 * The prompt is passed directly, so the agent wakes, does the work, and exits.
 *
 * Watches the crontab file for live changes — edit the file directly
 * and the scheduler picks it up without restart.
 *
 * Based on pi-cron by Espen Nilsen.
 */

import { spawn } from "node:child_process";
import * as fs from "node:fs";
import { loadJobs, getTabPath, matchesCron, DEFAULT_TIMEOUT_MS, type CronJob } from "./crontab.js";

// ── Types ───────────────────────────────────────────────────────

export interface CronSettings {
	autostart: boolean;
	activeHours: { start: string; end: string } | null;
	alertRoom: string;
	showOk: boolean;
}

export interface JobEvent {
	job: CronJob;
	startedAt: Date;
}

export interface JobCompleteEvent extends JobEvent {
	durationMs: number;
	ok: boolean;
	response?: string;
	error?: string;
}

export interface SchedulerCallbacks {
	onJobStart?: (event: JobEvent) => void;
	onJobComplete?: (event: JobCompleteEvent) => void;
	onReload?: (jobs: CronJob[]) => void;
	onAlert?: (message: string) => void;
}

// ── Subprocess runner ───────────────────────────────────────────

interface RunResult {
	stdout: string;
	stderr: string;
	exitCode: number;
}

function runPiSubprocess(
	prompt: string,
	cwd: string,
	timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<RunResult> {
	return new Promise((resolve) => {
		const args = ["-p", "--no-session", "--no-extensions", prompt];

		const child = spawn("pi", args, {
			cwd,
			stdio: ["ignore", "pipe", "pipe"],
			env: { ...process.env },
			timeout: timeoutMs,
		});

		let stdout = "";
		let stderr = "";

		child.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
		child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });

		child.on("close", (code) => {
			resolve({ stdout, stderr, exitCode: code ?? 1 });
		});

		child.on("error", (err) => {
			resolve({ stdout, stderr: stderr + "\n" + err.message, exitCode: 1 });
		});
	});
}

// ── Scheduler ───────────────────────────────────────────────────

const TICK_INTERVAL_MS = 30_000;

export class CronScheduler {
	private cwd: string;
	private settings: CronSettings;
	private callbacks: SchedulerCallbacks;
	private timer: ReturnType<typeof setInterval> | null = null;
	private watcher: fs.FSWatcher | null = null;
	private lastTickMinute = "";
	private running = new Set<string>();
	private jobs: CronJob[] = [];
	private runCount = 0;
	private okCount = 0;
	private errorCount = 0;

	constructor(cwd: string, settings: CronSettings, callbacks: SchedulerCallbacks = {}) {
		this.cwd = cwd;
		this.settings = settings;
		this.callbacks = callbacks;
	}

	// ── Lifecycle ───────────────────────────────────────────

	start(): void {
		if (this.timer) return;
		this.reload();
		this.startWatcher();
		this.tick(); // Immediate first tick
		this.timer = setInterval(() => this.tick(), TICK_INTERVAL_MS);
	}

	stop(): void {
		if (this.timer) {
			clearInterval(this.timer);
			this.timer = null;
		}
		this.stopWatcher();
	}

	isActive(): boolean {
		return this.timer !== null;
	}

	updateSettings(settings: CronSettings): void {
		this.settings = settings;
	}

	getStatus() {
		return {
			active: this.isActive(),
			jobCount: this.jobs.length,
			enabledCount: this.jobs.filter(j => !j.disabled).length,
			runningNames: [...this.running],
			runCount: this.runCount,
			okCount: this.okCount,
			errorCount: this.errorCount,
		};
	}

	// ── File watcher ────────────────────────────────────────

	private startWatcher(): void {
		this.stopWatcher();
		try {
			this.watcher = fs.watch(getTabPath(), { persistent: false }, () => {
				this.reload();
			});
			this.watcher.on("error", () => {
				// File might be temporarily gone during writes
			});
		} catch {
			// File doesn't exist yet — fine
		}
	}

	private stopWatcher(): void {
		if (this.watcher) {
			this.watcher.close();
			this.watcher = null;
		}
	}

	private reload(): void {
		this.jobs = loadJobs();
		this.callbacks.onReload?.(this.jobs);
	}

	// ── Public API ──────────────────────────────────────────

	list(): Array<CronJob & { running: boolean }> {
		return this.jobs.map(j => ({ ...j, running: this.running.has(j.name) }));
	}

	runNow(name: string): string {
		const job = this.jobs.find(j => j.name === name);
		if (!job) return `Job "${name}" not found.`;
		if (this.running.has(name)) return `Job "${name}" is already running.`;
		this.running.add(name);
		this.execute(job).finally(() => this.running.delete(name));
		return `✓ Triggered "${name}"`;
	}

	// ── Tick ────────────────────────────────────────────────

	private tick(): void {
		const now = new Date();
		const currentMinute = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${now.getHours()}-${now.getMinutes()}`;

		// Only fire once per minute
		if (currentMinute === this.lastTickMinute) return;
		this.lastTickMinute = currentMinute;

		// Active hours check
		if (!this.inActiveHours(now)) return;

		for (const job of this.jobs) {
			if (job.disabled || this.running.has(job.name)) continue;

			try {
				if (!matchesCron(job.schedule, now)) continue;
			} catch {
				continue;
			}

			this.running.add(job.name);
			this.execute(job).finally(() => this.running.delete(job.name));
		}
	}

	private async execute(job: CronJob): Promise<void> {
		const startedAt = new Date();
		this.callbacks.onJobStart?.({ job, startedAt });

		try {
			const result = await runPiSubprocess(job.prompt, this.cwd, job.timeoutMs);
			const durationMs = Date.now() - startedAt.getTime();
			this.runCount++;

			if (result.exitCode !== 0 && !result.stdout) {
				throw new Error(result.stderr || `Process exited with code ${result.exitCode}`);
			}

			this.okCount++;
			const response = result.stdout.trim().slice(0, 2000) || undefined;
			this.callbacks.onJobComplete?.({ job, startedAt, durationMs, ok: true, response });

			if (this.settings.showOk) {
				this.callbacks.onAlert?.(
					`✅ Cron "${job.name}" completed (${(durationMs / 1000).toFixed(1)}s)`
				);
			}
		} catch (err: any) {
			const durationMs = Date.now() - startedAt.getTime();
			this.runCount++;
			this.errorCount++;

			const errorMsg = err.message?.slice(0, 500) ?? "Unknown error";
			this.callbacks.onJobComplete?.({ job, startedAt, durationMs, ok: false, error: errorMsg });
			this.callbacks.onAlert?.(
				`❌ Cron "${job.name}" failed (${(durationMs / 1000).toFixed(1)}s): ${errorMsg}`
			);
		}
	}

	private inActiveHours(now: Date): boolean {
		if (!this.settings.activeHours) return true;
		const { start, end } = this.settings.activeHours;
		const currentMinutes = now.getHours() * 60 + now.getMinutes();

		const [startH, startM] = start.split(":").map(Number);
		const [endH, endM] = end.split(":").map(Number);
		const startMinutes = startH * 60 + startM;
		const endMinutes = endH * 60 + endM;

		// Handle overnight ranges (e.g., 22:00 - 06:00)
		if (endMinutes < startMinutes) {
			return currentMinutes >= startMinutes || currentMinutes < endMinutes;
		}
		return currentMinutes >= startMinutes && currentMinutes < endMinutes;
	}
}
