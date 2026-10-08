import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";

// CommonJS is intentional: Electron main loads this exact module.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRestartPolicy, dataDirId, reusable } = require("./backend-lifecycle.cjs") as {
  createRestartPolicy: (options?: { maxRestarts?: number; windowMs?: number; baseDelayMs?: number }) => {
    next(now?: number): number | null;
  };
  dataDirId: (dir: string) => string;
  reusable: (
    health: Record<string, unknown> | null,
    expected: { version: string; dataDir: string; strict: boolean },
  ) => { ok: boolean; reason?: string };
};

const DIR = "/tmp/mosael-data";
const mine = { status: "ok", app: "mosael", version: "1.8.0", data_dir_id: "40a9c9be4789eb9d" };

describe("端口上的后端能不能复用", () => {
  it("数据目录指纹和后端(core/lifeline)同一个算法", () => {
    expect(dataDirId(DIR)).toBe("40a9c9be4789eb9d");
  });

  it("打包版:版本和数据目录都对得上才复用", () => {
    const expected = { version: "1.8.0", dataDir: DIR, strict: true };
    expect(reusable(mine, expected).ok).toBe(true);
    expect(reusable({ ...mine, version: "1.7.0" }, expected).ok, "上次强杀留下的旧版孤儿").toBe(false);
    expect(reusable({ ...mine, data_dir_id: "0000" }, expected).ok, "指着另一份数据").toBe(false);
    expect(reusable({ status: "ok" }, expected).ok, "端口上是别的东西").toBe(false);
    expect(reusable(null, expected).ok).toBe(false);
  });

  it("开发时照旧宽松:手动起的 uvicorn 只要活着就用", () => {
    expect(reusable({ status: "ok" }, { version: "1.8.0", dataDir: DIR, strict: false }).ok).toBe(true);
  });
});

describe("崩溃重启的退避", () => {
  it("1s、2s、4s,五分钟里第四次就认输", () => {
    const policy = createRestartPolicy();
    expect([policy.next(0), policy.next(10), policy.next(20)]).toEqual([1000, 2000, 4000]);
    expect(policy.next(30)).toBeNull();
  });

  it("崩溃隔得够久就重新计数", () => {
    const policy = createRestartPolicy({ windowMs: 1000 });
    policy.next(0);
    policy.next(10);
    policy.next(20);
    expect(policy.next(5000)).toBe(1000);
  });
});

// ---------------------------------------------------------------- 后端的一生(createBackendSupervisor)

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createBackendSupervisor } = require("./backend-lifecycle.cjs") as {
  createBackendSupervisor: (options: Record<string, unknown>) => Supervisor;
};

interface Supervisor {
  start(options?: { initial?: boolean; onWaiting?: (elapsed: number) => void; deadlineMs?: number }): Promise<{ status: string; reason?: string; code?: unknown }>;
  retry(): Promise<{ status: string }>;
  shutdown(): Promise<void>;
  killNow(): void;
  stopForRestore(options?: { forceAfterMs?: number; giveUpAfterMs?: number }): Promise<boolean>;
  resumeAfterFailedRestore(): Promise<{ status: string }>;
  needsGracefulShutdown(): boolean;
  readonly running: boolean;
  readonly gaveUp: boolean;
}

/** 一个后端进程的替身:kill 记下来;`exit()` 模拟它退出。 */
class FakeProcess extends EventEmitter {
  exitCode: number | null = null;
  signalCode: string | null = null;
  kills: (string | undefined)[] = [];
  constructor(private readonly exitOnKill = true) {
    super();
  }
  kill(signal?: string) {
    this.kills.push(signal);
    if (this.exitOnKill) this.exit(null, signal ?? "SIGTERM");
    return true;
  }
  exit(code: number | null, signal: string | null = null) {
    if (this.exitCode !== null || this.signalCode) return;
    this.exitCode = code;
    this.signalCode = signal;
    this.emit("exit", code, signal);
  }
}

const healthy = { status: "ok", app: "mosael", version: "1.9.3", data_dir_id: "40a9c9be4789eb9d" };

/**
 * 一套假时钟:sleep 推进时间立刻回;schedule 记下来,`runScheduled` 手动触发(重拉的退避)。
 * `health(t)`:时间 t 时健康检查回什么。
 */
function harness({
  strict = true,
  platform = "darwin",
  health = (_now: number, _proc: FakeProcess | null): Record<string, unknown> | null => null,
  spawnProcess = () => new FakeProcess(),
  requestShutdown = async () => false,
}: {
  strict?: boolean;
  platform?: string;
  health?: (now: number, proc: FakeProcess | null) => Record<string, unknown> | null;
  spawnProcess?: () => FakeProcess | null;
  requestShutdown?: () => Promise<boolean>;
} = {}) {
  let clock = 0;
  const spawned: FakeProcess[] = [];
  const scheduled: { callback: () => void; ms: number }[] = [];
  const onGiveUp = vi.fn();
  const log = vi.fn();
  const current = () => {
    const last = spawned[spawned.length - 1];
    return last && last.exitCode === null && !last.signalCode ? last : null;
  };
  const supervisor = createBackendSupervisor({
    probe: async () => health(clock, current()),
    spawn: async () => {
      const proc = spawnProcess();
      if (proc) spawned.push(proc);
      return proc;
    },
    expected: { version: "1.9.3", dataDir: DIR, strict },
    platform,
    requestShutdown,
    onGiveUp,
    log,
    pollMs: 300,
    orphanGraceMs: 20_000,
    shutdownGraceMs: 50,
    sleep: async (ms: number) => {
      clock += ms;
    },
    now: () => clock,
    schedule: (callback: () => void, ms: number) => scheduled.push({ callback, ms }),
  });
  /** 触发排着的重拉,等它跑完。 */
  async function runScheduled() {
    const next = scheduled.shift();
    if (!next) throw new Error("nothing scheduled");
    next.callback();
    for (let i = 0; i < 50; i += 1) await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  return { supervisor, spawned, scheduled, onGiveUp, log, runScheduled, clockAt: () => clock };
}

/** 进程起来 `readyAfterMs` 之后才健康。 */
const readyAfter = (readyAfterMs: number) => {
  let bornAt: number | null = null;
  let born: FakeProcess | null = null;
  return (now: number, proc: FakeProcess | null) => {
    if (!proc) return null;
    if (proc !== born) {
      born = proc;
      bornAt = now;
    }
    return now - (bornAt ?? now) >= readyAfterMs ? healthy : null;
  };
};

describe("起后端:只要进程活着就等它就绪", () => {
  it("冷启动 / 升级迁移要 45 秒也照样等到,不在 30 秒时判失败;等的时候一直报进度", async () => {
    const { supervisor, spawned } = harness({ health: readyAfter(45_000) });
    const waited: number[] = [];
    const result = await supervisor.start({ initial: true, onWaiting: (elapsed) => waited.push(elapsed) });
    expect(result.status).toBe("ready");
    expect(spawned).toHaveLength(1);
    expect(spawned[0].kills, "等的时候没去杀它").toEqual([]);
    expect(Math.max(...waited)).toBeGreaterThanOrEqual(44_000);
  });

  it("进程退了才算没起来:报退出码,第一次启动不当作崩溃去重拉", async () => {
    const proc = new FakeProcess();
    const { supervisor, scheduled } = harness({
      spawnProcess: () => proc,
      health: (now) => {
        if (now >= 3000) proc.exit(3);
        return null;
      },
    });
    expect(await supervisor.start({ initial: true })).toEqual({ status: "exited", code: 3 });
    expect(scheduled).toEqual([]);
  });

  it("冒烟里没人看着:给了期限就按期限报超时", async () => {
    const { supervisor } = harness();
    expect((await supervisor.start({ initial: true, deadlineMs: 120_000 })).status).toBe("timeout");
  });

  it("人在主密钥那个框里选了退出:spawn 回 null,报 cancelled", async () => {
    const { supervisor } = harness({ spawnProcess: () => null });
    expect((await supervisor.start({ initial: true })).status).toBe("cancelled");
  });
});

describe("端口上已经有一个后端", () => {
  it("打包版:同版本同数据的是上一个壳的孤儿,等它自己退了再拉起自己的,不接管它", async () => {
    // 孤儿在 6 秒后随 lifeline 退出;之后是我们拉起的那个。
    const ownReady = readyAfter(1_000);
    const { supervisor, spawned } = harness({ health: (now, proc) => (proc ? ownReady(now, proc) : now < 6_000 ? healthy : null) });
    expect((await supervisor.start({ initial: true })).status).toBe("ready");
    expect(spawned, "自己拉起了一个").toHaveLength(1);
    expect(supervisor.running).toBe(true);
  });

  it("打包版:等了 20 秒它还不退,说端口被占,不硬起第二个", async () => {
    const { supervisor, spawned } = harness({ health: () => healthy });
    const result = await supervisor.start({ initial: true });
    expect(result.status).toBe("portTaken");
    expect(spawned).toEqual([]);
  });

  it("版本、数据对不上:直接说端口被占", async () => {
    const { supervisor, spawned } = harness({ health: () => ({ ...healthy, version: "1.0.0" }) });
    expect((await supervisor.start({ initial: true })).status).toBe("portTaken");
    expect(spawned).toEqual([]);
  });

  it("开发:手动起的 uvicorn 就用它", async () => {
    const { supervisor, spawned } = harness({ strict: false, health: () => ({ status: "ok" }) });
    expect((await supervisor.start({ initial: true })).status).toBe("reused");
    expect(spawned).toEqual([]);
  });
});

describe("意外退出:退避重拉,连崩认输,认输后能再试", () => {
  it("就绪过的后端崩了就按 1s 退避重拉;五分钟里第四次崩溃认输,告诉人最后一次怎么退的", async () => {
    const h = harness({ health: readyAfter(0) });
    expect((await h.supervisor.start({ initial: true })).status).toBe("ready");
    for (const delay of [1000, 2000, 4000]) {
      h.spawned[h.spawned.length - 1].exit(null, "SIGKILL");
      expect(h.scheduled.map((one) => one.ms)).toEqual([delay]);
      await h.runScheduled();
      expect(h.supervisor.running).toBe(true);
    }
    h.spawned[h.spawned.length - 1].exit(139);
    expect(h.scheduled).toEqual([]);
    expect(h.onGiveUp).toHaveBeenCalledWith(139);
    expect(h.supervisor.gaveUp).toBe(true);

    // 认输之后人点「再试一次」:重新计数、真的拉起来。
    expect((await h.supervisor.retry()).status).toBe("ready");
    expect(h.supervisor.gaveUp).toBe(false);
    expect(h.spawned).toHaveLength(5);
    // 重新计数:再崩一次是从 1 秒的退避重来,不是当场又认输。
    h.spawned[h.spawned.length - 1].exit(1);
    expect(h.scheduled.map((one) => one.ms)).toEqual([1000]);
    expect(h.onGiveUp).toHaveBeenCalledTimes(1);
  });

  it("正跑着的时候「重试」什么都不做", async () => {
    const h = harness({ health: readyAfter(0) });
    await h.supervisor.start({ initial: true });
    expect((await h.supervisor.retry()).status).toBe("running");
    expect(h.spawned).toHaveLength(1);
  });

  it("退出 / 恢复备份时的退出不算意外,不重拉", async () => {
    const h = harness({ health: readyAfter(0) });
    await h.supervisor.start({ initial: true });
    await h.supervisor.shutdown();
    expect(h.scheduled).toEqual([]);
    expect(h.onGiveUp).not.toHaveBeenCalled();
  });
});

describe("退出时收尾", () => {
  it("macOS / Linux:SIGTERM 就是「请你收尾」,发一次不等;之后进程退出的路上不再补第二个(uvicorn 收到第二个就不收尾了)", async () => {
    const proc = new FakeProcess(false);
    const h = harness({ spawnProcess: () => proc, health: readyAfter(0) });
    await h.supervisor.start({ initial: true });
    expect(h.supervisor.needsGracefulShutdown()).toBe(false);
    await h.supervisor.shutdown();
    h.supervisor.killNow();
    expect(proc.kills).toEqual(["SIGTERM"]);
  });

  it("Windows:先请它自己收尾、等它退;退了就不强杀", async () => {
    const proc = new FakeProcess(false);
    const requestShutdown = vi.fn(async () => {
      setTimeout(() => proc.exit(0), 5);
      return true;
    });
    const h = harness({ platform: "win32", spawnProcess: () => proc, health: readyAfter(0), requestShutdown });
    await h.supervisor.start({ initial: true });
    expect(h.supervisor.needsGracefulShutdown()).toBe(true);
    await h.supervisor.shutdown();
    expect(requestShutdown).toHaveBeenCalledOnce();
    expect(proc.kills).toEqual([]);
    expect(h.supervisor.needsGracefulShutdown()).toBe(false);
  });

  it("Windows:请不动(没有壳令牌)或者等不到它退,才强杀", async () => {
    const stubborn = new FakeProcess(false);
    const h = harness({ platform: "win32", spawnProcess: () => stubborn, health: readyAfter(0), requestShutdown: async () => true });
    await h.supervisor.start({ initial: true });
    await h.supervisor.shutdown();
    expect(stubborn.kills).toEqual([undefined]);

    const unasked = new FakeProcess(false);
    const h2 = harness({ platform: "win32", spawnProcess: () => unasked, health: readyAfter(0), requestShutdown: async () => false });
    await h2.supervisor.start({ initial: true });
    await h2.supervisor.shutdown();
    expect(unasked.kills).toEqual([undefined]);
  });
});

describe("恢复备份", () => {
  it("停掉我们拉起的那个(它退了不重拉);恢复没成就把它拉回来", async () => {
    const h = harness({ health: readyAfter(0) });
    await h.supervisor.start({ initial: true });
    expect(await h.supervisor.stopForRestore()).toBe(true);
    expect(h.spawned[0].kills).toEqual(["SIGTERM"]);
    expect(h.scheduled).toEqual([]);
    expect((await h.supervisor.resumeAfterFailedRestore()).status).toBe("ready");
    expect(h.spawned).toHaveLength(2);
  });

  it("后端不是我们拉起的(开发时手动起的):回 false,调用方说要由桌面应用起的后端", async () => {
    const h = harness({ strict: false, health: () => ({ status: "ok" }) });
    await h.supervisor.start({ initial: true });
    expect(await h.supervisor.stopForRestore()).toBe(false);
  });
});
