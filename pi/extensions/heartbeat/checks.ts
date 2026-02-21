/**
 * Heartbeat Checks — Periodic Awareness
 *
 * Three tiers of checks:
 *   PULSE   — Every heartbeat. Fast. Matrix messages, infra pings.
 *   BREATH  — Every 3rd beat. Medium. Custom script checks.
 *   TIDE    — Every 6th beat. Slow. Deep maintenance.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// ── Types ───────────────────────────────────────────────────

export interface CheckResult {
	name: string;
	ok: boolean;
	message: string;
	durationMs: number;
	data?: Record<string, any>;
}

export interface MatrixMessage {
	room: string;
	sender: string;
	content: string;
	timestamp: string;
}

type ExecFn = (cmd: string) => Promise<{ stdout: string; ok: boolean }>;

function makeExec(pi: ExtensionAPI): ExecFn {
	return async (cmd: string) => {
		const { stdout, code } = await pi.exec("bash", ["-c", cmd]);
		return { stdout: stdout.trim(), ok: code === 0 };
	};
}

async function timed(name: string, fn: () => Promise<{ ok: boolean; message: string; data?: Record<string, any> }>): Promise<CheckResult> {
	const start = Date.now();
	try {
		const result = await fn();
		return { name, ...result, durationMs: Date.now() - start };
	} catch (err: any) {
		return { name, ok: false, message: `Exception: ${err.message}`, durationMs: Date.now() - start };
	}
}

// ═══════════════════════════════════════════════════════════
// PULSE CHECKS — Every heartbeat (~15m)
// ═══════════════════════════════════════════════════════════

const MATRIX_WATERMARK_FILE = "/tmp/.heartbeat_matrix_watermarks.json";
type RoomWatermarks = Record<string, number>;

function readWatermarks(): RoomWatermarks {
	try {
		const fs = require("fs");
		return JSON.parse(fs.readFileSync(MATRIX_WATERMARK_FILE, "utf8"));
	} catch {
		return {};
	}
}

function writeWatermarks(wm: RoomWatermarks): void {
	try {
		const fs = require("fs");
		fs.writeFileSync(MATRIX_WATERMARK_FILE, JSON.stringify(wm));
	} catch { /* best effort */ }
}

/**
 * Read Matrix messages since last check.
 * Uses per-room watermarks to avoid re-reporting the same messages.
 *
 * @param prioritySenders  Matrix user IDs whose messages trigger urgent alerts
 * @param botSenders       Matrix user IDs to filter from reporting (but still advance watermarks past)
 */
export function checkMatrixMessages(exec: ExecFn, sinceMinutes: number, prioritySenders: string[] = [], botSenders: string[] = []): Promise<CheckResult> {
	return timed("Matrix", async () => {
		const watermarks = readWatermarks();

		// Try to read messages via the matrix-read skill (path configurable via env)
		const matrixReadPath = process.env.MATRIX_READ_SKILL_PATH || "./skills/matrix-read";
		const { stdout, ok } = await exec(
			`cd ${matrixReadPath} && ` +
			`python3 matrix_read.py --all --since ${sinceMinutes} --json 2>/dev/null`
		);

		if (!ok || !stdout) {
			// Connectivity check
			const { ok: whoamiOk } = await exec(
				`curl -sf --max-time 5 ` +
				`-H "Authorization: Bearer $MATRIX_ACCESS_TOKEN" ` +
				`"$MATRIX_HOMESERVER_URL/_matrix/client/v3/account/whoami" 2>/dev/null`
			);
			if (!whoamiOk) {
				return { ok: false, message: "Matrix unreachable", data: { messages: [] } };
			}
			return { ok: true, message: "Connected, no new messages", data: { messages: [] } };
		}

		try {
			const parsed = JSON.parse(stdout);
			const messages: MatrixMessage[] = [];
			const newWatermarks: RoomWatermarks = { ...watermarks };
			const botSet = new Set(botSenders);
			const prioritySet = new Set(prioritySenders);

			function extractContent(msg: any): string {
				let body = "";
				if (msg.content?.body) body = msg.content.body;
				else if (msg.content?.["m.relates_to"]?.key) return `[reaction: ${msg.content["m.relates_to"].key}]`;
				else if (msg.body) body = msg.body;
				else if (typeof msg.content === "string") body = msg.content;
				else return "";

				// Strip Matrix reply fallback
				if (body.startsWith("> ")) {
					const lines = body.split("\n");
					let idx = 0;
					while (idx < lines.length && lines[idx].startsWith("> ")) idx++;
					if (idx < lines.length && lines[idx].trim() === "") idx++;
					const cleaned = lines.slice(idx).join("\n").trim();
					if (cleaned) body = cleaned;
				}
				return body;
			}

			function isTextMessage(msg: any): boolean {
				return msg.type === "m.room.message";
			}

			function isReply(msg: any): boolean {
				const relates = msg.content?.["m.relates_to"] || {};
				return !!(relates["m.in_reply_to"]?.event_id || relates.rel_type === "m.thread");
			}

			function processRoom(room: string, msgs: any[]): void {
				const roomWatermark = watermarks[room] || 0;
				for (const msg of msgs) {
					const ts = msg.origin_server_ts || 0;
					if (ts > (newWatermarks[room] || 0)) newWatermarks[room] = ts;
					if (ts <= roomWatermark) continue;
					const relType = msg.content?.["m.relates_to"]?.rel_type;
					if (relType === "m.replace") continue;
					const sender = msg.sender || msg.user_id || "";
					if (botSet.has(sender)) continue;
					if (!isTextMessage(msg)) continue;
					const content = extractContent(msg);
					if (!content) continue;
					messages.push({
						room,
						sender,
						content: isReply(msg) ? `[reply] ${content}` : content,
						timestamp: ts ? String(ts) : "",
					});
				}
			}

			if (typeof parsed === "object" && !Array.isArray(parsed)) {
				for (const [room, msgs] of Object.entries(parsed)) {
					if (Array.isArray(msgs)) processRoom(room, msgs as any[]);
				}
			} else if (Array.isArray(parsed)) {
				processRoom("unknown", parsed);
			}

			writeWatermarks(newWatermarks);

			const count = messages.length;
			const priorityMsgs = messages.filter(m =>
				prioritySenders.some(ps => m.sender.includes(ps))
			);

			let msg = count === 0
				? "No new messages"
				: `${count} new message${count > 1 ? "s" : ""}`;

			if (priorityMsgs.length > 0) {
				msg += ` (${priorityMsgs.length} priority!)`;
			}

			return {
				ok: true,
				message: msg,
				data: { messages, priorityMessages: priorityMsgs },
			};
		} catch {
			const lines = stdout.split("\n").filter(l => l.trim());
			return {
				ok: true,
				message: lines.length > 0 ? `${lines.length} message line(s)` : "No new messages",
				data: { messages: [], raw: stdout.slice(0, 500) },
			};
		}
	});
}

/**
 * Quick infrastructure ping — ChromaDB, SQLite databases, disk space.
 * Database paths are read from HEARTBEAT_DB_PATHS env var (comma-separated).
 */
export function checkInfrastructure(exec: ExecFn): Promise<CheckResult> {
	return timed("Infra", async () => {
		const dbPathsEnv = process.env.HEARTBEAT_DB_PATHS || "";
		const { stdout } = await exec(`python3 -c "
import json, os, sqlite3
status = {}

# ChromaDB
try:
    import chromadb
    host = os.environ.get('CHROMADB_HOST', 'localhost')
    port = int(os.environ.get('CHROMADB_PORT', '8000'))
    c = chromadb.HttpClient(host=host, port=port)
    c.heartbeat()
    status['chromadb'] = True
except:
    status['chromadb'] = False

# SQLite databases (from env, comma-separated name:path pairs)
db_paths = os.environ.get('HEARTBEAT_DB_PATHS', '')
if db_paths:
    for entry in db_paths.split(','):
        entry = entry.strip()
        if ':' in entry:
            name, path = entry.split(':', 1)
        else:
            name = os.path.basename(entry)
            path = entry
        try:
            conn = sqlite3.connect(path.strip())
            conn.execute('SELECT 1')
            conn.close()
            status[name.strip()] = True
        except:
            status[name.strip()] = False

# Disk
try:
    st = os.statvfs('.')
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    pct = round((1 - free/total) * 100)
    status['disk_pct'] = pct
    status['disk_free_gb'] = round(free / (1024**3), 1)
except:
    status['disk_pct'] = -1

print(json.dumps(status))
" 2>/dev/null`);

		try {
			const s = JSON.parse(stdout);
			const down = Object.entries(s)
				.filter(([k, v]) => k !== "disk_pct" && k !== "disk_free_gb" && v === false)
				.map(([k]) => k);

			const diskWarning = (s.disk_pct ?? 0) >= 85;
			const parts: string[] = [];

			if (down.length > 0) parts.push(`⚠ ${down.join(", ")} down`);
			if (diskWarning) parts.push(`disk ${s.disk_pct}%`);
			if (parts.length === 0) parts.push(`all up, disk ${s.disk_pct}% (${s.disk_free_gb}GB free)`);

			return {
				ok: down.length === 0 && !diskWarning,
				message: parts.join("; "),
				data: { services: s },
			};
		} catch {
			return { ok: false, message: "Could not check infrastructure" };
		}
	});
}

// ═══════════════════════════════════════════════════════════
// ORCHESTRATOR
// ═══════════════════════════════════════════════════════════

export interface HeartbeatResult {
	beatNumber: number;
	tier: "pulse" | "breath" | "tide";
	ok: boolean;
	checks: CheckResult[];
	totalDurationMs: number;
	time: string;
	failedChecks: string[];
	briefing: string;
	/** Whether there's something urgent (priority message, critical failure) */
	urgent: boolean;
}

function assembleBriefing(checks: CheckResult[], tier: string, beatNumber: number): { briefing: string; urgent: boolean } {
	const lines: string[] = [];
	let urgent = false;

	const now = new Date();
	const timeStr = now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

	lines.push(`🫀 Heartbeat #${beatNumber} [${tier}] — ${timeStr}`);
	lines.push("");

	// Matrix messages
	const matrixCheck = checks.find(c => c.name === "Matrix");
	if (matrixCheck?.data?.messages?.length > 0) {
		const messages = matrixCheck.data.messages as MatrixMessage[];
		const priorityMsgs = matrixCheck.data.priorityMessages as MatrixMessage[] || [];

		if (priorityMsgs.length > 0) {
			urgent = true;
			lines.push(`📨 **${priorityMsgs.length} priority message${priorityMsgs.length > 1 ? "s" : ""}:**`);
			for (const msg of priorityMsgs.slice(0, 5)) {
				const preview = msg.content.length > 120 ? msg.content.slice(0, 120) + "…" : msg.content;
				lines.push(`   [${msg.room}] ${msg.sender}: ${preview}`);
			}
			lines.push("");
		}

		const otherMsgs = messages.filter(m =>
			!priorityMsgs.some(pm => pm.sender === m.sender && pm.timestamp === m.timestamp)
		);
		if (otherMsgs.length > 0) {
			lines.push(`💬 ${otherMsgs.length} other message${otherMsgs.length > 1 ? "s" : ""}`);
		}
	} else if (matrixCheck && !matrixCheck.ok) {
		urgent = true;
		lines.push(`⚠ Matrix: ${matrixCheck.message}`);
	}

	// Infrastructure
	const infraCheck = checks.find(c => c.name === "Infra");
	if (infraCheck && !infraCheck.ok) {
		urgent = true;
		lines.push(`⚠ Infra: ${infraCheck.message}`);
	} else if (infraCheck) {
		lines.push(`🏛 ${infraCheck.message}`);
	}

	// Failed checks summary
	const failed = checks.filter(c => !c.ok);
	if (failed.length > 0 && !lines.some(l => l.includes("⚠"))) {
		lines.push(`⚠ Failed: ${failed.map(c => c.name).join(", ")}`);
	}

	return { briefing: lines.join("\n"), urgent };
}

export async function runHeartbeat(pi: ExtensionAPI, beatNumber: number, sinceMinutes: number, prioritySenders: string[] = []): Promise<HeartbeatResult> {
	const startTime = Date.now();
	const exec = makeExec(pi);

	const isTide = beatNumber % 6 === 0 && beatNumber > 0;
	const isBreath = beatNumber % 3 === 0 && beatNumber > 0;
	const tier = isTide ? "tide" : isBreath ? "breath" : "pulse";

	const checks: CheckResult[] = [];

	// Bot senders to filter (configurable via env, comma-separated)
	const botSendersEnv = process.env.HEARTBEAT_BOT_SENDERS || "";
	const botSenders = botSendersEnv ? botSendersEnv.split(",").map(s => s.trim()) : [];

	// PULSE — always run
	const pulseChecks = await Promise.all([
		checkMatrixMessages(exec, sinceMinutes, prioritySenders, botSenders),
		checkInfrastructure(exec),
	]);
	checks.push(...pulseChecks);

	// BREATH and TIDE tiers are available for custom checks via cron jobs.
	// The heartbeat itself stays lightweight — Matrix + infra only.

	const failedChecks = checks.filter(c => !c.ok).map(c => c.name);
	const { briefing, urgent } = assembleBriefing(checks, tier, beatNumber);

	return {
		beatNumber,
		tier,
		ok: failedChecks.length === 0,
		checks,
		totalDurationMs: Date.now() - startTime,
		time: new Date().toISOString(),
		failedChecks,
		briefing,
		urgent,
	};
}
