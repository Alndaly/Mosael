import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const manifest = JSON.parse(
  readFileSync(new URL("../manifest.json", import.meta.url), "utf8"),
) as {
  permissions?: string[];
  optional_host_permissions?: string[];
  host_permissions?: string[];
  content_scripts?: Array<{ matches?: string[]; world?: string }>;
};

describe("browser extension permissions", () => {
  it("keeps broad frame-capture access optional", () => {
    expect(manifest.permissions).toContain("activeTab");
    expect(manifest.optional_host_permissions).toContain("<all_urls>");
  });

  it("covers the official domain families used by supported video sites", () => {
    expect(manifest.host_permissions).toEqual(expect.arrayContaining([
      "https://*.youtube.com/*",
      "https://youtu.be/*",
      "https://*.youtube-nocookie.com/*",
      "https://*.googlevideo.com/*",
      "https://*.ytimg.com/*",
      "https://*.bilibili.com/*",
      "https://*.hdslb.com/*",
      "https://*.bilivideo.com/*",
      "https://*.bilivideo.cn/*",
      "https://*.pornhub.com/*",
    ]));
  });

  it("injects both transcript and player bridges on every supported site", () => {
    expect(manifest.content_scripts).toHaveLength(2);
    for (const script of manifest.content_scripts || []) {
      expect(script.matches).toEqual(expect.arrayContaining([
        "https://*.youtube.com/*",
        "https://*.bilibili.com/*",
        "https://*.pornhub.com/*",
      ]));
    }
  });
});
