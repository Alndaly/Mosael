/**
 * 自定义 CSS 的文件这一侧:文件在哪、监听盯的是什么。
 *
 * 「盯目录而不是盯文件」是这里唯一容易做错、而且**只在真机上才发作**的地方:多数编辑器
 * 保存是「写临时文件 + 改名覆盖」,原文件的 inode 就此作废,`fs.watch(文件)` 之后再也不响。
 * 症状是「头一次改生效,之后怎么改都没反应」——单测里手写 writeFileSync 是复现不出来的,
 * 因为那不换 inode。所以这里钉的是**监听的目标**,而不是它响没响。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import path from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  userData: "/tmp/mosael-test-userdata",
  watch: vi.fn(() => ({ close: vi.fn() })),
  existsSync: vi.fn(),
  readFileSync: vi.fn(),
  writeFileSync: vi.fn(),
  mkdirSync: vi.fn(),
  send: vi.fn(),
}));

vi.mock("electron", () => ({
  app: { getPath: (name: string) => (name === "userData" ? h.userData : `/tmp/${name}`) },
  shell: { showItemInFolder: vi.fn(), openPath: vi.fn().mockResolvedValue("") },
}));

vi.mock("node:fs", () => ({
  default: {
    watch: h.watch,
    existsSync: h.existsSync,
    readFileSync: h.readFileSync,
    writeFileSync: h.writeFileSync,
    mkdirSync: h.mkdirSync,
  },
}));

const { customCss, customCssPath, ensureCustomCss, readCustomCss } = await import("./customCss");

beforeEach(() => {
  for (const fn of [h.watch, h.existsSync, h.readFileSync, h.writeFileSync, h.mkdirSync, h.send]) fn.mockReset();
  h.watch.mockReturnValue({ close: vi.fn() } as never);
});

describe("自定义 CSS 的文件位置", () => {
  it("住在客户端自己的 userData 里,不在后端的数据目录", () => {
    // 后端的家是 ~/.mosael,而后端可能压根不在这台机器上 —— 外观是逐设备的。
    expect(customCssPath()).toBe(path.join(h.userData, "custom.css"));
    expect(customCssPath()).not.toContain(".mosael");
  });

  it("读不到时给空串,不抛 —— 没有自定义样式不该让应用出问题", () => {
    h.readFileSync.mockImplementation(() => {
      throw new Error("ENOENT");
    });
    expect(readCustomCss()).toBe("");
  });

  it("文件已存在就不覆盖用户写的东西", () => {
    h.existsSync.mockReturnValue(true);
    ensureCustomCss();
    expect(h.writeFileSync).not.toHaveBeenCalled();
  });

  it("不存在才按模板建一个", () => {
    h.existsSync.mockReturnValue(false);
    ensureCustomCss();
    expect(h.writeFileSync).toHaveBeenCalledOnce();
    expect(String(h.writeFileSync.mock.calls[0][1])).toContain("--primary");
  });
});

describe("存盘即生效的监听", () => {
  it("盯的是目录,不是文件 —— 编辑器原子保存会换掉文件的 inode", () => {
    customCss.register({ getWindow: () => null, showWindow: () => {}, isDev: false, iconPath: "" });

    expect(h.watch).toHaveBeenCalledOnce();
    const target = h.watch.mock.calls[0][0];
    expect(target).toBe(h.userData);
    expect(target).not.toContain("custom.css");
  });

  it("监听不上也不该让应用起不来", () => {
    h.watch.mockImplementation(() => {
      throw new Error("EMFILE");
    });
    expect(() =>
      customCss.register({ getWindow: () => null, showWindow: () => {}, isDev: false, iconPath: "" }),
    ).not.toThrow();
  });
});
