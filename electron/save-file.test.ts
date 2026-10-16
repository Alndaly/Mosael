/**
 * 「保存到本地」的主进程那一半(见 save-file.cjs):弹的是哪种保存框、字节写到哪儿去了、取消 / 失败时
 * 用户原来那个文件有没有被动过。
 *
 * `dialog` 换掉(不弹真框),文件系统用真的(临时目录里跑)—— 「写下去的是不是那些字节」只有真落盘才量得准。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

// CommonJS is intentional: main.cjs loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const saveFile = require("./save-file.cjs") as {
  createSaveDesk: (options: {
    dialog: { showSaveDialog: (...args: unknown[]) => Promise<unknown> };
    downloadsDir: string;
    title: string;
    idleMs?: number;
    log?: (line: string) => void;
  }) => Desk;
  safeName: (raw: string) => string;
  saveDialogOptions: (title: string, defaultPath: string) => Record<string, unknown>;
  MAX_SESSIONS: number;
};

type BeginResult = { status: "ready"; id: string } | { status: "cancelled" } | { status: "failed"; error: string };
type WriteResult = { status: "writing"; received: number } | { status: "failed"; error: string };
type EndResult = { status: "saved"; path: string } | { status: "failed"; error: string };

type Desk = {
  begin: (request: { name: string }, window?: unknown) => Promise<BeginResult>;
  write: (request: { id: string; bytes: Uint8Array }) => Promise<WriteResult>;
  end: (request: { id: string }) => Promise<EndResult>;
  abort: (request: { id: string }) => Promise<void>;
  dispose: () => Promise<void>;
  count: () => number;
};

type Picked = string | null;

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

/** 一套台账 + 它的下载目录;`picked` 是保存框依次要选中的文件名(null / 给完了就当用户取消)。 */
function deskOf(picked: Picked[], idleMs?: number) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-save-"));
  roots.push(root);
  const downloads = path.join(root, "Downloads");
  fs.mkdirSync(downloads);
  const queue = [...picked];
  const showSaveDialog = vi.fn(async (..._args: unknown[]) => {
    const next = queue.shift();
    return next === undefined || next === null ? { canceled: true } : { canceled: false, filePath: path.join(downloads, next) };
  });
  const desk = saveFile.createSaveDesk({
    dialog: { showSaveDialog },
    downloadsDir: downloads,
    title: "保存到本地",
    idleMs,
    log: () => undefined,
  });
  return { desk, showSaveDialog, downloads, target: (name: string) => path.join(downloads, name) };
}

const text = (value: string) => new TextEncoder().encode(value);
const parts = (chunks: Uint8Array[]) => Buffer.concat(chunks.map((one) => Buffer.from(one)));

describe("保存到本地", () => {
  it("选了路径:字节原样写到那儿,临时文件收尾后不留;保存框的默认名是建议名、默认目录是下载目录,挂在发起的窗口上", async () => {
    const target = "voice.wav";
    const { desk, showSaveDialog, downloads, target: at } = deskOf([target]);
    const window = { id: 1 };

    const begun = await desk.begin({ name: "配音.wav" }, window);
    expect(begun).toMatchObject({ status: "ready" });
    expect(showSaveDialog).toHaveBeenCalledWith(window, {
      title: "保存到本地",
      defaultPath: path.join(downloads, "配音.wav"),
      properties: ["showOverwriteConfirmation", "createDirectory"],
    });

    const id = (begun as { id: string }).id;
    await expect(desk.write({ id, bytes: text("first ") })).resolves.toEqual({ status: "writing", received: 6 });
    await expect(desk.write({ id, bytes: text("second") })).resolves.toEqual({ status: "writing", received: 12 });
    await expect(desk.end({ id })).resolves.toEqual({ status: "saved", path: at(target) });

    expect(fs.readFileSync(at(target)), "写下去的就是交上来的那些字节").toEqual(parts([text("first "), text("second")]));
    expect(fs.readdirSync(downloads), "收尾之后目标旁边不留 .partial").toEqual([target]);
    expect(desk.count()).toBe(0);
  });

  it("取消:静默回 cancelled,不建临时文件、不写一个字节、不报错", async () => {
    const { desk, downloads } = deskOf([null]);

    await expect(desk.begin({ name: "笔记.md" }, null)).resolves.toEqual({ status: "cancelled" });
    expect(fs.readdirSync(downloads)).toEqual([]);
    expect(desk.count()).toBe(0);
  });

  it("没有窗口就不挂在窗口上(照 path-picker 同一套写法)", async () => {
    const { desk, showSaveDialog } = deskOf(["a.txt"]);

    await desk.begin({ name: "a.txt" }, null);
    expect(showSaveDialog.mock.calls[0]).toHaveLength(1);
  });

  it("建议名里的路径出不了下载目录(默认名只当保存框里那一段)", async () => {
    const { desk, showSaveDialog, downloads } = deskOf([null]);

    await desk.begin({ name: "../../evil.txt" }, { id: 1 });
    const [, options] = showSaveDialog.mock.calls[0] as [unknown, { defaultPath: string }];
    expect(path.dirname(options.defaultPath)).toBe(downloads);
  });

  it("写失败(改名改不动):临时文件撤掉,用户选的那个路径原样没被动", async () => {
    const { desk, downloads, target } = deskOf(["taken.txt"]);
    // 目标位置上放一个目录:收尾那一步的 rm 会失败(这正是「写不下去」时的那条路)。
    fs.mkdirSync(target("taken.txt"));

    const begun = (await desk.begin({ name: "taken.txt" }, null)) as { id: string };
    await desk.write({ id: begun.id, bytes: text("bytes") });
    const ended = await desk.end({ id: begun.id });

    expect(ended.status).toBe("failed");
    expect(fs.readdirSync(downloads), "临时文件撤了,用户的东西还在").toEqual(["taken.txt"]);
    expect(fs.statSync(target("taken.txt")).isDirectory()).toBe(true);
    expect(desk.count()).toBe(0);
  });

  it("收尾之后再写、或者拿一个没开过的 id 来,都回 failed(不抛)", async () => {
    const { desk } = deskOf(["a.txt"]);
    const begun = (await desk.begin({ name: "a.txt" }, null)) as { id: string };
    await desk.end({ id: begun.id });

    await expect(desk.write({ id: begun.id, bytes: text("x") })).resolves.toMatchObject({ status: "failed" });
    await expect(desk.end({ id: "0f8fad5b-d9cb-469f-a165-70867728950e" })).resolves.toMatchObject({ status: "failed" });
    await expect(desk.abort({ id: "0f8fad5b-d9cb-469f-a165-70867728950e" })).resolves.toBeUndefined();
  });

  it("渲染层写到一半没了:闲置超时把临时文件撤掉(用户选的那个路径不碰)", async () => {
    const { desk, downloads } = deskOf(["half.bin"], 20);
    const begun = (await desk.begin({ name: "half.bin" }, null)) as { id: string };
    await desk.write({ id: begun.id, bytes: text("half") });
    expect(fs.readdirSync(downloads), "写下去的是临时文件").toHaveLength(1);

    // 等条件(临时文件没了),不等时间:真计时器一兑现,这条就过 —— 机器忙只会慢一点,不会红。
    await vi.waitFor(() => expect(fs.readdirSync(downloads), "临时文件没了,且没有变成目标文件").toEqual([]));
    expect(desk.count()).toBe(0);
  });

  it("退出时还挂着的都撤掉(dispose)", async () => {
    const { desk, downloads } = deskOf(["one.bin", "two.bin"]);
    await desk.begin({ name: "one.bin" }, null);
    await desk.begin({ name: "two.bin" }, null);
    expect(desk.count()).toBe(2);

    await desk.dispose();

    expect(fs.readdirSync(downloads)).toEqual([]);
    expect(desk.count()).toBe(0);
  });

  it("没写完的份数有上限:满了就不弹框了", async () => {
    const names = Array.from({ length: saveFile.MAX_SESSIONS }, (_, index) => `many-${index}.bin`);
    const { desk, showSaveDialog, downloads } = deskOf([...names]);
    for (const name of names) await desk.begin({ name }, null);

    await expect(desk.begin({ name: "one-too-many.bin" }, null)).resolves.toMatchObject({ status: "failed" });
    expect(showSaveDialog).toHaveBeenCalledTimes(saveFile.MAX_SESSIONS);
    await desk.dispose();
    expect(fs.readdirSync(downloads)).toEqual([]);
  });
});

describe("建议文件名", () => {
  it("路径分隔符和系统不收的字符换掉,开头的点和结尾的点 / 空格去掉", () => {
    expect(saveFile.safeName("../../evil.txt")).toBe("_.._evil.txt");
    expect(saveFile.safeName("a/b\\c.txt")).toBe("a_b_c.txt");
    expect(saveFile.safeName("a:b?.txt")).toBe("a_b_.txt");
    expect(saveFile.safeName("..")).toBe("mosael-download");
    expect(saveFile.safeName("   ")).toBe("mosael-download");
    expect(saveFile.safeName(".hidden")).toBe("hidden");
    expect(saveFile.safeName("trailing. ")).toBe("trailing");
    expect(saveFile.safeName("x".repeat(400))).toHaveLength(180);
  });

  it("保存框的选项:默认名 + 覆盖前先问、能当场新建文件夹", () => {
    expect(saveFile.saveDialogOptions("保存到本地", "/Users/me/Downloads/a.bin")).toEqual({
      title: "保存到本地",
      defaultPath: "/Users/me/Downloads/a.bin",
      properties: ["showOverwriteConfirmation", "createDirectory"],
    });
  });
});
