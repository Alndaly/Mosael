/**
 * 开发时拉起 Electron 的那一层:主进程以「要重启」的退出码退出时再拉一遍(vite、后端都不受影响),别的退出照原样
 * 退 —— `pnpm dev` 用 concurrently -k 跑,Electron 那一栏一退,整组跟着收,这是「真退出」该有的样子。
 */
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

import { describe, expect, it, vi } from "vitest";

const { superviseElectron, RESTART_EXIT_CODE } = createRequire(import.meta.url)("./dev-loop.cjs") as {
  RESTART_EXIT_CODE: number;
  superviseElectron: (opts: {
    spawn: (env: Record<string, string>) => EventEmitter & { kill(signal?: string): void };
    onExit: (code: number) => void;
    log?: (line: string) => void;
    signals?: EventEmitter;
  }) => void;
};

function fakeChild() {
  return Object.assign(new EventEmitter(), { kill: vi.fn() });
}

describe("开发时拉起 Electron", () => {
  it("主进程要重启:再拉一遍,并告诉它可以要求重启(带上重启用的退出码)", () => {
    const children = [fakeChild(), fakeChild()];
    const envs: Array<Record<string, string>> = [];
    const onExit = vi.fn();
    superviseElectron({ spawn: (env) => (envs.push(env), children[envs.length - 1]), onExit, log: () => undefined });
    expect(envs).toHaveLength(1);
    expect(envs[0].MOSAEL_DEV_RESTART_CODE).toBe(String(RESTART_EXIT_CODE));
    children[0].emit("exit", RESTART_EXIT_CODE, null);
    expect(envs).toHaveLength(2);
    expect(onExit).not.toHaveBeenCalled();
    children[1].emit("exit", 0, null);
    expect(onExit).toHaveBeenCalledWith(0);
  });

  it("别的退出(关掉应用、崩了、被信号杀了)照原样退,不再拉", () => {
    const onExit = vi.fn();
    const child = fakeChild();
    superviseElectron({ spawn: () => child, onExit, log: () => undefined });
    child.emit("exit", null, "SIGKILL");
    expect(onExit).toHaveBeenCalledWith(1);
    const crashed = fakeChild();
    const onCrash = vi.fn();
    superviseElectron({ spawn: () => crashed, onExit: onCrash, log: () => undefined });
    crashed.emit("exit", 3, null);
    expect(onCrash).toHaveBeenCalledWith(3);
  });

  it("concurrently 收工时(SIGTERM / SIGINT)把 Electron 一起带走", () => {
    const signals = new EventEmitter();
    const child = fakeChild();
    superviseElectron({ spawn: () => child, onExit: vi.fn(), log: () => undefined, signals });
    signals.emit("SIGTERM");
    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
  });

  it("pnpm dev 经这一层拉起 Electron", () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "../frontend/package.json"), "utf8")) as { scripts: Record<string, string> };
    expect(pkg.scripts["electron:dev"]).toContain("node ../electron/dev-loop.cjs ../electron/main.cjs");
    expect(pkg.scripts["electron:dev"]).not.toMatch(/&& electron \.\.\/electron\/main\.cjs/);
  });
});
