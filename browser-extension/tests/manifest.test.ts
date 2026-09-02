import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const manifest = JSON.parse(
  readFileSync(new URL("../manifest.json", import.meta.url), "utf8"),
) as {
  permissions?: string[];
  host_permissions?: string[];
  content_scripts?: Array<{ matches?: string[]; world?: string }>;
};

describe("browser extension permissions", () => {
  it("can run the generic adapter on every HTTP(S) site yt-dlp may support", () => {
    expect(manifest.permissions).toContain("activeTab");
    expect(manifest.host_permissions).toEqual(["<all_urls>"]);
  });

  it("injects both transcript and player bridges on every supported site", () => {
    expect(manifest.content_scripts).toHaveLength(2);
    for (const script of manifest.content_scripts || []) {
      expect(script.matches).toEqual(["*://*/*"]);
    }
  });
});
