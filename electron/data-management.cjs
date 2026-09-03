const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { strToU8, zipSync } = require("fflate");

const DIAGNOSTIC_FORMAT_VERSION = 1;
const MAX_LOG_BYTES = 512 * 1024;
const RESTORE_MARKER = ".mosael-restore.json";

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function replaceLiteral(text, value, replacement) {
  if (!value) return text;
  return text.replace(new RegExp(escapeRegExp(String(value)), "g"), replacement);
}

function redactDiagnosticText(value, options = {}) {
  let text = String(value ?? "");
  // More specific locations must be replaced before HOME or the useful label is lost.
  text = replaceLiteral(text, options.dataDir, "<DATA_DIR>");
  text = replaceLiteral(text, options.userDataDir, "<USER_DATA_DIR>");
  text = replaceLiteral(text, options.homeDir, "<HOME>");
  for (const secret of options.secrets || []) {
    if (typeof secret === "string" && secret.length >= 4) text = replaceLiteral(text, secret, "<REDACTED>");
  }
  text = text.replace(/\bBearer\s+[^\s"']+/gi, "Bearer <REDACTED>");
  text = text.replace(
    /\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|secret)(["']?\s*[:=]\s*["']?)([^\s,;}&"']+)/gi,
    (_match, key, separator) => `${key}${separator}<REDACTED>`,
  );
  text = text.replace(/\b(sk|pk|ghp|gho|hf|xox[baprs])[-_][A-Za-z0-9_-]{8,}/g, "$1-<REDACTED>");
  text = text.replace(/(?<=:\/\/)[^/\s:@]+:[^/\s@]+(?=@)/g, "<REDACTED>");
  return text;
}

function readTail(file, limit = MAX_LOG_BYTES) {
  try {
    const stat = fs.statSync(file);
    if (!stat.isFile()) return "";
    const size = Math.min(stat.size, limit);
    const buffer = Buffer.alloc(size);
    const fd = fs.openSync(file, "r");
    try {
      fs.readSync(fd, buffer, 0, size, Math.max(0, stat.size - size));
    } finally {
      fs.closeSync(fd);
    }
    return buffer.toString("utf8");
  } catch {
    return "";
  }
}

function diagnosticEntries(options = {}) {
  const redaction = {
    dataDir: options.dataDir,
    userDataDir: options.userDataDir,
    homeDir: options.homeDir,
    secrets: options.secrets,
  };
  const manifest = {
    format: "mosael-diagnostics",
    version: DIAGNOSTIC_FORMAT_VERSION,
    generated_at: new Date().toISOString(),
    app_version: String(options.appVersion || "unknown"),
    platform: String(options.platform || process.platform),
    arch: String(options.arch || process.arch),
    node_version: process.versions.node,
    electron_version: process.versions.electron || "",
    included_logs: [],
  };
  const entries = {};
  for (const file of options.logFiles || []) {
    const content = readTail(file);
    if (!content) continue;
    const name = path.basename(file).replace(/[^A-Za-z0-9_.-]/g, "_");
    const entry = `diagnostics/${name}`;
    entries[entry] = strToU8(redactDiagnosticText(content, redaction));
    manifest.included_logs.push(entry);
  }
  entries["manifest.json"] = strToU8(`${JSON.stringify(manifest, null, 2)}\n`);
  return entries;
}

async function writeDiagnosticArchive(destination, options = {}) {
  const archive = zipSync(diagnosticEntries(options), { level: 6 });
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, archive, { mode: 0o600 });
  return destination;
}

function restoreStagePath(dataDir, stageId) {
  if (!/^[a-f0-9]{32}$/.test(stageId)) throw new TypeError("invalid restore stage id");
  const resolved = path.resolve(dataDir);
  const name = path.basename(resolved);
  if (!name || resolved === path.parse(resolved).root) throw new TypeError("invalid data directory");
  return path.join(path.dirname(resolved), `.${name}.restore-${stageId}`);
}

function readRestoreMarker(directory) {
  try {
    return JSON.parse(fs.readFileSync(path.join(directory, RESTORE_MARKER), "utf8"));
  } catch (error) {
    throw new Error("restore staging marker is missing or invalid", { cause: error });
  }
}

function activateStagedRestore(dataDir, stageId) {
  const resolved = path.resolve(dataDir);
  const stage = restoreStagePath(resolved, stageId);
  const marker = readRestoreMarker(stage);
  if (marker.format !== "mosael-backup" || marker.version !== 1 || marker.stage_id !== stageId) {
    throw new Error("restore staging marker does not match the requested backup");
  }
  if (!fs.statSync(path.join(stage, "mosael.db")).isFile()) throw new Error("staged database is missing");
  if (!fs.statSync(resolved).isDirectory()) throw new Error("current data directory is missing");

  const previousName = `.${path.basename(resolved)}.before-restore-${randomUUID()}`;
  const previousDir = path.join(path.dirname(resolved), previousName);
  fs.renameSync(resolved, previousDir);
  try {
    fs.renameSync(stage, resolved);
    fs.writeFileSync(
      path.join(resolved, RESTORE_MARKER),
      JSON.stringify({ ...marker, activated: true, previous_dir: previousName }),
      { encoding: "utf8", mode: 0o600 },
    );
  } catch (error) {
    try {
      if (fs.existsSync(resolved)) fs.renameSync(resolved, stage);
      fs.renameSync(previousDir, resolved);
    } catch {
      // Preserve the original error; both directories remain adjacent for manual recovery.
    }
    throw error;
  }
  return { previousDir };
}

async function finalizeActivatedRestore(dataDir) {
  const resolved = path.resolve(dataDir);
  const markerPath = path.join(resolved, RESTORE_MARKER);
  if (!fs.existsSync(markerPath)) return false;
  const marker = readRestoreMarker(resolved);
  const previousPattern = new RegExp(
    `^${escapeRegExp(`.${path.basename(resolved)}.before-restore-`)}[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`,
  );
  if (
    marker.activated !== true
    || typeof marker.previous_dir !== "string"
    || !previousPattern.test(marker.previous_dir)
  ) {
    return false;
  }
  const previousDir = path.join(path.dirname(resolved), marker.previous_dir);
  await fs.promises.rm(previousDir, { recursive: true, force: true });
  await fs.promises.rm(markerPath, { force: true });
  return true;
}

module.exports = {
  DIAGNOSTIC_FORMAT_VERSION,
  MAX_LOG_BYTES,
  RESTORE_MARKER,
  activateStagedRestore,
  diagnosticEntries,
  redactDiagnosticText,
  finalizeActivatedRestore,
  writeDiagnosticArchive,
};
