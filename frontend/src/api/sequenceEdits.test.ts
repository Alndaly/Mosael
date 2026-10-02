/**
 * 时间线的编辑请求带着「照着第几版做的」,撞上 409 时把服务端附上的最新序列交给订阅方。
 *
 * 此前编辑请求什么版本号都不带:两个人同时剪,后到的那一步照样在自己屏幕上那份过时的时间线上算落点。
 * 服务端现在会拒(409,附最新的一版、说清是谁改的)—— 客户端这一侧要做的是:每一步都报版本号、连着做的两步
 * 不把自己的上一步当成别人的改动、撞上 409 时换掉手里的缓存并弹服务端那句话。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function reply(status: number, payload: unknown) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const sequence = (revision: number) => ({ id: "s1", project_id: "p", revision, tracks: [] });

describe("时间线编辑的版本号", () => {
  it("每一步都带 base_revision", async () => {
    const { moveClip } = await import("@/api/domains/editor");
    fetchMock.mockResolvedValue(reply(200, sequence(6)));

    await moveClip({ id: "s1", revision: 5 }, "c1", { timeline_start: 2 });

    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/sequences/s1/clips/c1/move?base_revision=5");
  });

  it("连着做的第二步报的是第一步回来的版本,不是手里那份旧的", async () => {
    const { moveClip, setClipGain } = await import("@/api/domains/editor");
    fetchMock.mockResolvedValueOnce(reply(200, sequence(11))).mockResolvedValueOnce(reply(200, sequence(12)));

    await moveClip({ id: "s1", revision: 10 }, "c1", { timeline_start: 2 });
    await setClipGain({ id: "s1", revision: 10 }, "c1", 0.5, false);

    expect(String(fetchMock.mock.calls[1][0])).toContain("base_revision=11");
  });

  it("撞上 409:订阅方拿到最新的序列,抛出来的是服务端那句话(说清是谁改的)", async () => {
    const { onSequenceConflict, trimClip } = await import("@/api/domains/editor");
    const latest = sequence(42);
    fetchMock.mockResolvedValue(
      reply(409, {
        detail: { code: "sequence_revision_conflict", message: "mate刚改过这条时间线", base_revision: 30, current_revision: 42, sequence: latest },
      }),
    );
    const seen: unknown[] = [];
    const stop = onSequenceConflict((next) => seen.push(next));

    await expect(trimClip({ id: "s1", revision: 30 }, "c1", { timeline_start: 0, src_in: 0, src_out: 1 })).rejects.toThrow(
      "mate刚改过这条时间线",
    );
    stop();
    expect(seen).toEqual([latest]);
  });
});
