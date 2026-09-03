import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SETTINGS = path.resolve(__dirname);

describe("settings component ownership", () => {
  it("keeps the view focused on navigation and composition", () => {
    const source = fs.readFileSync(path.join(SETTINGS, "SettingsView.tsx"), "utf8");

    expect(source).not.toContain("function AccountSection");
    expect(source).not.toContain("function AppearanceSection");
    expect(source).not.toContain("function BackendSection");
    expect(source.split("\n").length).toBeLessThanOrEqual(300);
  });

  it("gives account, appearance and backend settings explicit owners", () => {
    for (const file of ["AccountSection.tsx", "AppearanceSection.tsx", "BackendSection.tsx"]) {
      expect(fs.existsSync(path.join(SETTINGS, file)), file).toBe(true);
    }
  });
});
