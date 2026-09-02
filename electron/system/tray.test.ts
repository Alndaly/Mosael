import fs from "node:fs";
import path from "node:path";

import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: {},
  Menu: {},
  nativeImage: {},
  nativeTheme: { shouldUseDarkColors: false },
  Tray: class {},
}));

const { resolveTrayAsset } = await import("./tray");

const ctx = {
  getWindow: () => null,
  showWindow: () => undefined,
  isDev: false,
  iconPath: "/build/icon.png",
  trayTemplatePath: "/build/trayTemplate.png",
  trayLightPath: "/build/tray-light.png",
  trayDarkPath: "/build/tray-dark.png",
};

function pngSize(file: string): [number, number] {
  const bytes = fs.readFileSync(file);
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

describe("常驻状态栏图标", () => {
  it("macOS 使用模板图，让系统替标记适配菜单栏明暗", () => {
    expect(resolveTrayAsset(ctx, "darwin", false)).toEqual({
      path: ctx.trayTemplatePath,
      template: true,
      dedicated: true,
    });
  });

  it("Windows 根据系统主题选择同一标记的深浅版本", () => {
    expect(resolveTrayAsset(ctx, "win32", false).path).toBe(ctx.trayLightPath);
    expect(resolveTrayAsset(ctx, "win32", true).path).toBe(ctx.trayDarkPath);
  });

  it("专用资源没配置时仍退回应用图标", () => {
    const bare = { ...ctx, trayTemplatePath: undefined, trayLightPath: undefined, trayDarkPath: undefined };
    expect(resolveTrayAsset(bare, "darwin", false).path).toBe(ctx.iconPath);
    expect(resolveTrayAsset(bare, "win32", true).path).toBe(ctx.iconPath);
  });

  it("随包资源包含平台需要的 1x/2x 尺寸", () => {
    const build = path.resolve(import.meta.dirname, "../../build");
    expect(pngSize(path.join(build, "trayTemplate.png"))).toEqual([18, 18]);
    expect(pngSize(path.join(build, "trayTemplate@2x.png"))).toEqual([36, 36]);
    expect(pngSize(path.join(build, "tray-light.png"))).toEqual([16, 16]);
    expect(pngSize(path.join(build, "tray-light@2x.png"))).toEqual([32, 32]);
    expect(pngSize(path.join(build, "tray-dark.png"))).toEqual([16, 16]);
    expect(pngSize(path.join(build, "tray-dark@2x.png"))).toEqual([32, 32]);
  });
});
