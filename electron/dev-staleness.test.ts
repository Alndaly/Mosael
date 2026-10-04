/**
 * 开发时主进程过期的判断:主进程启动时加载的那几份产物(main.cjs、publish / system / preload 这几个 bundle、
 * 同目录的其余 .cjs)后来变了,而正在跑的还是旧的。按内容判,不按「文件被写过」判 —— watch 一启动会把没变的
 * bundle 原样再写一遍,那不算过期。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { createStalenessWatcher } = createRequire(import.meta.url)("./dev-staleness.cjs") as {
  createStalenessWatcher: (opts: {
    dir: string;
    onChange: (files: string[]) => void;
    debounceMs?: number;
    watch?: (dir: string, listener: (event: string, name: string | null) => void) => { close(): void };
  }) => { stale(): string[]; close(): void };
};

let dir: string;
let fire: (name: string) => void;
let closed = false;
const fakeWatch = (_dir: string, listener: (event: string, name: string | null) => void) => {
  fire = (name) => listener("change", name);
  return { close: () => (closed = true) };
};

beforeEach(() => {
  vi.useFakeTimers();
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-stale-"));
  fs.writeFileSync(path.join(dir, "main.cjs"), "main v1");
  fs.writeFileSync(path.join(dir, "publish.bundle.cjs"), "publish v1");
  fs.writeFileSync(path.join(dir, "notes.md"), "not loaded by the main process");
  closed = false;
});

afterEach(() => {
  vi.useRealTimers();
  fs.rmSync(dir, { recursive: true, force: true });
});

describe("开发时主进程过期", () => {
  it("启动之后某份产物的内容变了:算过期,告诉调用方是哪几份", () => {
    const changes: string[][] = [];
    const watcher = createStalenessWatcher({ dir, onChange: (files) => changes.push(files), debounceMs: 100, watch: fakeWatch });
    fs.writeFileSync(path.join(dir, "publish.bundle.cjs"), "publish v2");
    fire("publish.bundle.cjs");
    vi.advanceTimersByTime(150);
    expect(changes.at(-1)).toEqual(["publish.bundle.cjs"]);
    expect(watcher.stale()).toEqual(["publish.bundle.cjs"]);

    fs.writeFileSync(path.join(dir, "main.cjs"), "main v2");
    fire("main.cjs");
    vi.advanceTimersByTime(150);
    expect(watcher.stale()).toEqual(["main.cjs", "publish.bundle.cjs"]);
  });

  it("原样重写(watch 启动时重编了一遍、内容没变)不算;改回原样就不再算", () => {
    const changes: string[][] = [];
    const watcher = createStalenessWatcher({ dir, onChange: (files) => changes.push(files), debounceMs: 100, watch: fakeWatch });
    fs.writeFileSync(path.join(dir, "publish.bundle.cjs"), "publish v1");
    fire("publish.bundle.cjs");
    vi.advanceTimersByTime(150);
    expect(watcher.stale()).toEqual([]);
    expect(changes).toEqual([]);

    fs.writeFileSync(path.join(dir, "main.cjs"), "main v2");
    fire("main.cjs");
    vi.advanceTimersByTime(150);
    fs.writeFileSync(path.join(dir, "main.cjs"), "main v1");
    fire("main.cjs");
    vi.advanceTimersByTime(150);
    expect(watcher.stale()).toEqual([]);
    expect(changes.at(-1)).toEqual([]);
  });

  it("一连串写入只判一次(debounce);不是主进程加载的文件不管;新出现的 .cjs 算过期", () => {
    const changes: string[][] = [];
    const watcher = createStalenessWatcher({ dir, onChange: (files) => changes.push(files), debounceMs: 100, watch: fakeWatch });
    fs.writeFileSync(path.join(dir, "main.cjs"), "main v2");
    fire("main.cjs");
    vi.advanceTimersByTime(50);
    fire("main.cjs");
    vi.advanceTimersByTime(150);
    expect(changes).toHaveLength(1);

    fs.writeFileSync(path.join(dir, "notes.md"), "changed");
    fire("notes.md");
    fs.writeFileSync(path.join(dir, "fresh.cjs"), "new module");
    fire("fresh.cjs");
    vi.advanceTimersByTime(150);
    expect(watcher.stale()).toEqual(["fresh.cjs", "main.cjs"]);
    watcher.close();
    expect(closed).toBe(true);
  });
});
