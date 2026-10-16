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

  it("gives account, appearance, backend and local-app settings explicit owners", () => {
    //: 「本机应用」是 4777fa580 从「后端」拆出来的一页 —— 它和这几页一样,是外壳不认识的一块,
    //: 得有自己的组件文件;拆出去之后留一份在这里一起看住(页面在、组件没了,是静默的白屏)。
    for (const file of ["AccountSection.tsx", "AppearanceSection.tsx", "BackendSection.tsx", "LocalAppSection.tsx"]) {
      expect(fs.existsSync(path.join(SETTINGS, file)), file).toBe(true);
    }
  });
});
