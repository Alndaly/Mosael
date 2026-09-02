import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

import { afterEach, describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { MIGRATION_MARKER, migrateLegacyUserData } = require("./user-data-migration.cjs") as {
  MIGRATION_MARKER: string;
  migrateLegacyUserData: (options: { target: string; legacyCandidates: string[] }) => {
    status: string;
    backup?: string | null;
  };
};

const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

describe("Electron userData rename migration", () => {
  it("backs up an already-created Mosael directory before adopting Open Studio", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-user-data-"));
    temporaryDirectories.push(root);
    const target = path.join(root, "Mosael");
    const legacy = path.join(root, "Open Studio");
    fs.mkdirSync(target);
    fs.mkdirSync(legacy);
    fs.writeFileSync(path.join(target, "new-preferences"), "backup me");
    fs.writeFileSync(path.join(legacy, "panel-layout.json"), "legacy layout");

    const first = migrateLegacyUserData({ target, legacyCandidates: [legacy] });

    expect(first.status).toBe("migrated");
    expect(fs.readFileSync(path.join(target, "panel-layout.json"), "utf8")).toBe("legacy layout");
    expect(fs.existsSync(path.join(target, MIGRATION_MARKER))).toBe(true);
    expect(fs.readFileSync(path.join(first.backup!, "new-preferences"), "utf8")).toBe("backup me");

    // A retained copy-fallback source cannot cause the migration to run twice.
    fs.mkdirSync(legacy);
    expect(migrateLegacyUserData({ target, legacyCandidates: [legacy] }).status).toBe(
      "already-migrated",
    );
  });
});
