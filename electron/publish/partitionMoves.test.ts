/**
 * 具名浏览器会话的登录分区搬家:后端迁移写下「谁搬到哪」,这里在磁盘上搬。
 *
 * 用真目录跑:这件事唯一的风险就在磁盘上 —— 搬错了方向、盖掉了一份更新的登录、或者在用着的分区底下挪目录。
 */
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { applyPartitionMove, partitionDir } from "./partitionMoves";

let userData = "";

beforeEach(() => {
  userData = mkdtempSync(join(tmpdir(), "mosael-partitions-"));
});

afterEach(() => {
  rmSync(userData, { recursive: true, force: true });
});

function seed(dir: string, cookie: string): void {
  mkdirSync(join(userData, "Partitions", dir), { recursive: true });
  writeFileSync(join(userData, "Partitions", dir, "Cookies"), cookie);
}

const move = { id: "m1", old_partition: "persist:rpa-XHS", new_partition: "persist:rpa-ws1-0123456789abcdef" };

describe("登录分区搬家", () => {
  it("旧分区的目录搬到新名字底下(Electron 落盘时把分区名转小写)", () => {
    seed("rpa-xhs", "logged-in");
    expect(applyPartitionMove(userData, move)).toEqual({ status: "done", reason: "" });
    expect(existsSync(join(userData, "Partitions", "rpa-xhs"))).toBe(false);
    expect(readFileSync(join(userData, "Partitions", "rpa-ws1-0123456789abcdef", "Cookies"), "utf8")).toBe("logged-in");
  });

  it("新目录已经在了就不搬:那是一份更新的登录,不拿旧的盖它", () => {
    seed("rpa-xhs", "old");
    seed("rpa-ws1-0123456789abcdef", "newer");
    expect(applyPartitionMove(userData, move)?.status).toBe("skipped");
    expect(readFileSync(join(userData, "Partitions", "rpa-ws1-0123456789abcdef", "Cookies"), "utf8")).toBe("newer");
    expect(existsSync(join(userData, "Partitions", "rpa-xhs"))).toBe(true);
  });

  it("旧目录不在(这台电脑上没登录过)记成 skipped,说清原因", () => {
    const outcome = applyPartitionMove(userData, move);
    expect(outcome?.status).toBe("skipped");
    expect(outcome?.reason).toMatch(/nothing on disk/);
  });

  it("这个进程正用着其中一个分区就先不搬,下次启动再说", () => {
    seed("rpa-xhs", "logged-in");
    expect(applyPartitionMove(userData, move, (partition) => partition === move.old_partition)).toBeNull();
    expect(existsSync(join(userData, "Partitions", "rpa-xhs"))).toBe(true);
  });

  it("不是这两条规则造出来的分区名不碰", () => {
    expect(partitionDir(userData, "ephemeral-abc")).toBeNull();
    expect(partitionDir(userData, "persist:../../etc")).toBeNull();
    expect(applyPartitionMove(userData, { ...move, new_partition: "persist:../escape" })?.status).toBe("skipped");
  });
});
