/**
 * Memory Extension — Persistent Agent Memory
 *
 * Structured tools for persistent memory:
 *
 *   memory_write  — Write to MEMORY.md (section-aware) or daily logs
 *   memory_read   — Read MEMORY.md, daily logs, or list available logs
 *   memory_search — Search across MEMORY.md, daily logs, and ChromaDB notes
 *
 * Daily logs live at .pi/memory/YYYY-MM-DD.md — simple timestamped entries
 * that give chronological context. They complement ChromaDB's semantic search
 * with "what happened today, in order."
 *
 * Based on pi-memory by Espen Nilsen, with ChromaDB integration.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { Type } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// ── Paths ───────────────────────────────────────────────────────

// Paths are configurable via env vars, with sensible defaults
const MEMORY_PATH = process.env.MEMORY_MD_PATH || path.join(process.cwd(), "MEMORY.md");
const DAILY_DIR = process.env.MEMORY_DAILY_DIR || path.join(process.cwd(), ".pi", "memory");

function todayStr(): string {
	const d = new Date();
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function yesterdayStr(): string {
	const d = new Date();
	d.setDate(d.getDate() - 1);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dailyPath(date?: string): string {
	return path.join(DAILY_DIR, `${date ?? todayStr()}.md`);
}

function readFileOr(filepath: string, fallback = ""): string {
	try {
		return fs.readFileSync(filepath, "utf-8");
	} catch {
		return fallback;
	}
}

function ensureDir(dir: string): void {
	fs.mkdirSync(dir, { recursive: true });
}

function escapeRegex(str: string): string {
	return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// ── Public helpers (used by wake.ts) ────────────────────────────

export function getTodayLog(): string {
	return readFileOr(dailyPath());
}

export function getYesterdayLog(): string {
	return readFileOr(dailyPath(yesterdayStr()));
}

export function listDailyFiles(): string[] {
	try {
		return fs.readdirSync(DAILY_DIR)
			.filter(f => f.endsWith(".md"))
			.sort()
			.reverse();
	} catch {
		return [];
	}
}

// ── Tool result helper ──────────────────────────────────────────

function text(s: string) {
	return { content: [{ type: "text" as const, text: s }], details: {} };
}

// ── Extension Entry ─────────────────────────────────────────────

export default function (pi: ExtensionAPI) {
	ensureDir(DAILY_DIR);

	// ── memory_write tool ─────────────────────────────────────

	pi.registerTool({
		name: "memory_write",
		label: "Memory Write",
		description:
			"Write to persistent memory. " +
			"target 'daily' appends a timestamped entry to today's log (.pi/memory/YYYY-MM-DD.md). " +
			"target 'long_term' updates MEMORY.md — provide a section name to find and replace that " +
			"section's content, or omit section to append to the end of the file. " +
			"Use daily logs for session notes and running context. " +
			"Use long_term for curated facts, status updates, and decisions that should persist.",
		parameters: Type.Object({
			target: Type.String({
				description: "Where to write: 'daily' (append to today's log) or 'long_term' (edit MEMORY.md)",
			}),
			content: Type.String({
				description: "The content to write",
			}),
			section: Type.Optional(
				Type.String({
					description:
						"For long_term only: section header to find and replace (e.g. 'Current Status'). " +
						"Matches ## headings. If the section exists, its content is replaced. " +
						"If it doesn't exist, a new section is appended. " +
						"If omitted, content is appended to end of MEMORY.md.",
				}),
			),
		}),

		async execute(_toolCallId, params) {
			const { target, content, section } = params as { target: string; content: string; section?: string };

			if (target === "daily") {
				ensureDir(DAILY_DIR);
				const now = new Date();
				const time = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
				const entry = `### ${time}\n\n${content}`;
				const fp = dailyPath();

				if (!readFileOr(fp)) {
					fs.writeFileSync(fp, `# Daily Log — ${todayStr()}\n\n${entry}\n`);
				} else {
					fs.appendFileSync(fp, "\n" + entry + "\n");
				}

				return text(`✓ Appended to daily log (${todayStr()} ${time})`);
			}

			if (target === "long_term") {
				const existing = readFileOr(MEMORY_PATH);

				if (section) {
					// Section-aware replacement: find ## Section and replace its content
					// until the next ## heading or end of file
					const pattern = new RegExp(
						`(## ${escapeRegex(section)}\\n)([\\s\\S]*?)(?=\\n## |$)`,
						"m",
					);
					const match = existing.match(pattern);

					if (match) {
						const updated = existing.replace(
							pattern,
							(_, header) => `${header}\n${content}\n`,
						);
						fs.writeFileSync(MEMORY_PATH, updated);
						return text(`✓ Updated section "${section}" in MEMORY.md`);
					} else {
						// Section doesn't exist — add it
						fs.appendFileSync(MEMORY_PATH, `\n## ${section}\n\n${content}\n`);
						return text(`✓ Added new section "${section}" to MEMORY.md`);
					}
				}

				// No section specified — append to end
				fs.appendFileSync(MEMORY_PATH, "\n" + content + "\n");
				return text("✓ Appended to MEMORY.md");
			}

			return text(`Unknown target "${target}". Use "daily" or "long_term".`);
		},
	});

	// ── memory_search tool ────────────────────────────────────

	pi.registerTool({
		name: "memory_search",
		label: "Memory Search",
		description:
			"Search across all memory sources: MEMORY.md, daily logs, and ChromaDB notes. " +
			"Returns matching lines with context from files, plus semantic results from ChromaDB. " +
			"Use this when you need to recall something from past sessions or find a specific fact.",
		parameters: Type.Object({
			query: Type.String({
				description: "Search term or phrase (case-insensitive for files, semantic for ChromaDB)",
			}),
			limit: Type.Optional(
				Type.Number({
					description: "Max results per source (default: 10)",
				}),
			),
		}),

		async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
			const { query, limit: maxResults } = params as { query: string; limit?: number };
			const limit = maxResults ?? 10;
			const results: string[] = [];

			// 1. Search MEMORY.md
			const memContent = readFileOr(MEMORY_PATH);
			if (memContent) {
				const fileResults = searchInContent(memContent, query, limit);
				if (fileResults.length > 0) {
					results.push(`**MEMORY.md** (${fileResults.length} matches):`);
					for (const r of fileResults) {
						results.push(`  Line ${r.lineNum}: ${r.context}`);
					}
				}
			}

			// 2. Search daily logs (last 14 days)
			const dailyFiles = listDailyFiles().slice(0, 14);
			let dailyMatches = 0;
			for (const file of dailyFiles) {
				const content = readFileOr(path.join(DAILY_DIR, file));
				const fileResults = searchInContent(content, query, 3);
				if (fileResults.length > 0) {
					const date = file.replace(".md", "");
					results.push(`**${date}** (${fileResults.length} matches):`);
					for (const r of fileResults) {
						results.push(`  ${r.context}`);
					}
					dailyMatches += fileResults.length;
					if (dailyMatches >= limit) break;
				}
			}

			// 3. Search ChromaDB notes
			try {
				const noteSkillPath = process.env.NOTE_SKILL_PATH || "./skills/take-note";
				const { stdout, code } = await pi.exec("bash", ["-c",
					`cd ${noteSkillPath} && ` +
					`python3 note.py --search '${query.replace(/'/g, "'\\''")}' --limit ${limit} 2>/dev/null`
				]);
				if (code === 0 && stdout.trim()) {
					results.push(`**ChromaDB Notes:**\n${stdout.trim()}`);
				}
			} catch { /* ChromaDB might be down */ }

			if (results.length === 0) {
				return text(`No results found for "${query}" across MEMORY.md, daily logs, or ChromaDB notes.`);
			}

			return text(`Search results for "${query}":\n\n${results.join("\n\n")}`);
		},
	});

	// ── memory_read tool ──────────────────────────────────────

	pi.registerTool({
		name: "memory_read",
		label: "Memory Read",
		description:
			"Read persistent memory. " +
			"target 'long_term' reads MEMORY.md. " +
			"target 'daily' reads a daily log (default: today). " +
			"target 'list' shows available daily log files.",
		parameters: Type.Object({
			target: Type.String({
				description: "What to read: 'long_term', 'daily', or 'list'",
			}),
			date: Type.Optional(
				Type.String({
					description: "For daily: date in YYYY-MM-DD format (defaults to today)",
				}),
			),
		}),

		async execute(_toolCallId, params) {
			const { target, date } = params as { target: string; date?: string };

			if (target === "list") {
				const files = listDailyFiles();
				if (files.length === 0) return text("No daily logs yet.");
				const list = files.map(f => `- ${f.replace(".md", "")}`).join("\n");
				return text(`Daily logs (${files.length}):\n${list}`);
			}

			if (target === "long_term") {
				return text(readFileOr(MEMORY_PATH, "(No MEMORY.md found)"));
			}

			if (target === "daily") {
				const d = date ?? todayStr();
				return text(readFileOr(dailyPath(d), `(No daily log for ${d})`));
			}

			return text(`Unknown target "${target}". Use "long_term", "daily", or "list".`);
		},
	});
}

// ── File search helper ──────────────────────────────────────────

interface SearchResult {
	lineNum: number;
	context: string;
}

function searchInContent(content: string, query: string, limit: number): SearchResult[] {
	const lowerQuery = query.toLowerCase();
	const lines = content.split("\n");
	const results: SearchResult[] = [];

	for (let i = 0; i < lines.length; i++) {
		if (!lines[i].toLowerCase().includes(lowerQuery)) continue;
		// Include surrounding context (1 line before, 1 after)
		const ctx = lines.slice(Math.max(0, i - 1), Math.min(lines.length, i + 2));
		results.push({ lineNum: i + 1, context: ctx.join("\n") });
		if (results.length >= limit) break;
	}

	return results;
}
