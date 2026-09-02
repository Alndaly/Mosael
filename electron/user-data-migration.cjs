const fs = require("node:fs");
const path = require("node:path");

const MIGRATION_MARKER = ".mosael-migrated-from-open-studio";

function nextBackupPath(target) {
  const base = `${target}.bak-before-open-studio-migration`;
  if (!fs.existsSync(base)) return base;
  let suffix = 2;
  while (fs.existsSync(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

function migrateLegacyUserData({ target, legacyCandidates }) {
  const legacy = legacyCandidates.find((candidate) => fs.existsSync(candidate));
  if (!legacy) return { status: "no-legacy-data", target };
  if (fs.existsSync(path.join(target, MIGRATION_MARKER))) {
    return { status: "already-migrated", target, source: legacy };
  }

  let backup = null;
  if (fs.existsSync(target)) {
    backup = nextBackupPath(target);
    fs.renameSync(target, backup);
  }

  let sourcePreserved = false;
  try {
    try {
      fs.renameSync(legacy, target);
    } catch {
      fs.cpSync(legacy, target, { recursive: true, errorOnExist: false });
      sourcePreserved = true;
    }
    fs.writeFileSync(
      path.join(target, MIGRATION_MARKER),
      JSON.stringify({ source: legacy, migratedAt: new Date().toISOString(), sourcePreserved }),
      "utf8",
    );
  } catch (error) {
    if (backup && fs.existsSync(backup)) {
      const failed = `${target}.failed-open-studio-migration`;
      if (fs.existsSync(target) && !fs.existsSync(failed)) fs.renameSync(target, failed);
      fs.renameSync(backup, target);
    }
    throw error;
  }

  return {
    status: sourcePreserved ? "copied" : "migrated",
    target,
    source: legacy,
    backup,
    sourcePreserved,
  };
}

module.exports = { MIGRATION_MARKER, migrateLegacyUserData };
