/**
 * Cron — File-based crontab parser and writer.
 *
 * Format (one job per line):
 *   <min> <hour> <dom> <month> <dow>  <name>  [channel:<ch>]  [disabled]  <prompt>
 *
 * Lines starting with # are comments. Blank lines are ignored.
 * The file lives at .pi/cron.tab (project-local).
 *
 * Based on pi-cron by Espen Nilsen.
 */

import * as fs from "node:fs";
import * as path from "node:path";

// ── Types ───────────────────────────────────────────────────────

export interface CronJob {
	name: string;
	schedule: string;
	prompt: string;
	channel: string;
	disabled: boolean;
	timeoutMs: number;
}

export const DEFAULT_TIMEOUT_MS = 900_000; // 15 minutes

// ── Path management ─────────────────────────────────────────────

let tabPath = ".pi/cron.tab";

export function setTabPath(p: string): void { tabPath = p; }
export function getTabPath(): string { return tabPath; }

// ── Parser ──────────────────────────────────────────────────────

export function parse(content: string): CronJob[] {
	const jobs: CronJob[] = [];

	for (const raw of content.split("\n")) {
		const line = raw.trim();
		if (!line || line.startsWith("#")) continue;

		const tokens = line.split(/\s+/);
		if (tokens.length < 7) continue; // 5 cron fields + name + at least 1 word of prompt

		const schedule = tokens.slice(0, 5).join(" ");
		const name = tokens[5];

		let idx = 6;
		let channel = "general";
		let disabled = false;
		let timeoutMs = DEFAULT_TIMEOUT_MS;

		// Parse optional flags before the prompt
		while (idx < tokens.length) {
			if (tokens[idx].startsWith("channel:")) {
				channel = tokens[idx].slice(8);
				idx++;
			} else if (tokens[idx].startsWith("timeout:")) {
				// timeout in minutes, e.g. timeout:30
				const mins = parseInt(tokens[idx].slice(8), 10);
				if (!isNaN(mins) && mins > 0) timeoutMs = mins * 60_000;
				idx++;
			} else if (tokens[idx] === "disabled") {
				disabled = true;
				idx++;
			} else {
				break;
			}
		}

		const prompt = tokens.slice(idx).join(" ");
		if (!prompt) continue;

		jobs.push({ name, schedule, prompt, channel, disabled, timeoutMs });
	}

	return jobs;
}

// ── Serializer ──────────────────────────────────────────────────

export function serialize(jobs: CronJob[]): string {
	const lines = [
		"# cron.tab — Scheduled jobs",
		"# Format: <min> <hour> <dom> <month> <dow>  <name>  [channel:<ch>]  [timeout:<min>]  [disabled]  <prompt>",
		"#",
		"# The schedule follows standard cron syntax:",
		"#   min(0-59) hour(0-23) dom(1-31) month(1-12) dow(0-6, 0=Sun)",
		"#   * = any, */N = every N, N-M = range, N,M = list",
		"#",
		"# Examples:",
		"#   0 9 * * 1-5  morning-brief  Check messages and summarize the day",
		"#   */30 * * * *  metrics-pulse  channel:data  Ingest platform metrics",
		"#   0 2 * * *  night-work  Run the overnight work session from OVERNIGHT.md",
		"#   0 * * * *  housekeeping  disabled  Run the housekeeping patrol from HOUSEKEEPING.md",
		"",
	];

	for (const job of jobs) {
		const flags = [];
		if (job.channel !== "general") flags.push(`channel:${job.channel}`);
		if (job.timeoutMs && job.timeoutMs !== DEFAULT_TIMEOUT_MS) {
			flags.push(`timeout:${Math.round(job.timeoutMs / 60_000)}`);
		}
		if (job.disabled) flags.push("disabled");
		const flagStr = flags.length > 0 ? "  " + flags.join("  ") : "";
		lines.push(`${job.schedule}  ${job.name}${flagStr}  ${job.prompt}`);
	}

	return lines.join("\n") + "\n";
}

// ── File I/O ────────────────────────────────────────────────────

export function loadJobs(): CronJob[] {
	try {
		const content = fs.readFileSync(tabPath, "utf-8");
		return parse(content);
	} catch {
		return [];
	}
}

export function saveJobs(jobs: CronJob[]): void {
	fs.mkdirSync(path.dirname(tabPath), { recursive: true });
	fs.writeFileSync(tabPath, serialize(jobs), "utf-8");
}

export function ensureTabFile(): void {
	if (!fs.existsSync(tabPath)) {
		saveJobs([]);
	}
}

// ── CRUD helpers ────────────────────────────────────────────────

export function addJob(job: CronJob): boolean {
	const jobs = loadJobs();
	if (jobs.find(j => j.name === job.name)) return false;
	jobs.push(job);
	saveJobs(jobs);
	return true;
}

export function removeJob(name: string): boolean {
	const jobs = loadJobs();
	const filtered = jobs.filter(j => j.name !== name);
	if (filtered.length === jobs.length) return false;
	saveJobs(filtered);
	return true;
}

export function updateJob(name: string, updates: Partial<Pick<CronJob, "schedule" | "prompt" | "channel" | "disabled" | "timeoutMs">>): boolean {
	const jobs = loadJobs();
	const job = jobs.find(j => j.name === name);
	if (!job) return false;
	if (updates.schedule !== undefined) job.schedule = updates.schedule;
	if (updates.prompt !== undefined) job.prompt = updates.prompt;
	if (updates.channel !== undefined) job.channel = updates.channel;
	if (updates.disabled !== undefined) job.disabled = updates.disabled;
	if (updates.timeoutMs !== undefined) job.timeoutMs = updates.timeoutMs;
	saveJobs(jobs);
	return true;
}

export function getJob(name: string): CronJob | undefined {
	return loadJobs().find(j => j.name === name);
}

// ── Cron expression matching ────────────────────────────────────

function parseField(field: string, min: number, max: number): Set<number> {
	const values = new Set<number>();

	for (const part of field.split(",")) {
		const [rangeStr, stepStr] = part.split("/");
		const step = stepStr ? parseInt(stepStr, 10) : 1;

		if (step < 1 || isNaN(step)) {
			throw new Error(`Invalid step "${stepStr}" in field "${field}"`);
		}

		let lo: number, hi: number;

		if (rangeStr === "*") {
			lo = min;
			hi = max;
		} else if (rangeStr.includes("-")) {
			const [a, b] = rangeStr.split("-");
			lo = parseInt(a, 10);
			hi = parseInt(b, 10);
		} else {
			lo = parseInt(rangeStr, 10);
			hi = lo;
		}

		if (isNaN(lo) || isNaN(hi)) {
			throw new Error(`Invalid value in field "${field}"`);
		}
		if (lo < min || hi > max) {
			throw new Error(`Value out of range in "${field}" (allowed ${min}-${max})`);
		}

		for (let i = lo; i <= hi; i += step) {
			values.add(i);
		}
	}

	return values;
}

export function matchesCron(expr: string, date: Date): boolean {
	const fields = expr.trim().split(/\s+/);
	if (fields.length !== 5) {
		throw new Error(`Invalid cron expression (need 5 fields): "${expr}"`);
	}

	return (
		parseField(fields[0], 0, 59).has(date.getMinutes()) &&
		parseField(fields[1], 0, 23).has(date.getHours()) &&
		parseField(fields[2], 1, 31).has(date.getDate()) &&
		parseField(fields[3], 1, 12).has(date.getMonth() + 1) &&
		parseField(fields[4], 0, 6).has(date.getDay())
	);
}

export function validateCron(expr: string): string | null {
	try {
		matchesCron(expr, new Date());
		return null;
	} catch (err: any) {
		return err.message;
	}
}
