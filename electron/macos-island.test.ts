import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";

import { createMacosIsland, encodeState, parseIslandOutput, toWire } from "./macos-island.cjs";

class FakeChild extends EventEmitter {
  stdin = { destroyed: false, write: vi.fn(), end: vi.fn() };
  stdout = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  stderr = Object.assign(new EventEmitter(), { setEncoding: vi.fn() });
  kill = vi.fn();
}

describe("macOS 灵动岛原生桥", () => {
  it("只把原生认识的字段送过去,不序列化 React 图标和回调", () => {
    const wire = toWire({
      id: "job:1",
      state: "ongoing",
      title: "生成图片",
      detail: "第 3 / 4 张",
      progress: 1.4,
      priority: 2,
      icon: () => null,
      onOpen: () => {},
    });
    expect(wire).toEqual({ id: "job:1", state: "ongoing", title: "生成图片", detail: "第 3 / 4 张", progress: 1, priority: 2 });
    expect(encodeState([wire])).toBe('{"activities":[{"id":"job:1","state":"ongoing","title":"生成图片","detail":"第 3 / 4 张","progress":1,"priority":2}]}\n');
  });

  it("原生回传的 open 行交给主进程,非协议行忽略", () => {
    expect(parseIslandOutput('{"type":"open","id":"job:1"}')).toEqual({ type: "open", id: "job:1" });
    expect(parseIslandOutput("not json")).toBeNull();
    expect(parseIslandOutput('{"type":"log"}')).toBeNull();
  });

  it("启动后写入最新快照,退出时释放管道", () => {
    const child = new FakeChild();
    const island = createMacosIsland({
      binaryPath: "/tmp/mosael-island",
      spawn: (() => child) as never,
      exists: () => true,
      platform: "darwin",
      onOpen: vi.fn(),
    });
    expect(island.start()).toBe(true);
    island.setActivities([{ id: "job:1", state: "ongoing", title: "生成图片" }]);
    expect(child.stdin.write).toHaveBeenLastCalledWith('{"activities":[{"id":"job:1","state":"ongoing","title":"生成图片"}]}\n');
    island.dispose();
    expect(child.stdin.end).toHaveBeenCalled();
    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
  });

  it("非 macOS 不启动", () => {
    const island = createMacosIsland({ binaryPath: "/x", platform: "win32", exists: () => true });
    expect(island.start()).toBe(false);
  });
});
