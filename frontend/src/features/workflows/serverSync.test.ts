import { describe, expect, it } from "vitest";

import { syncFromServer, type SyncState } from "./serverSync";

/** 把一串先后发生的事喂进去,拿回每一步的判断 —— 这条逻辑的 bug 全是"顺序"引起的。 */
function run(start: SyncState, steps: { updatedAt: string; graphHash: string; dirty: boolean }[]) {
  let state = start;
  return steps.map((step) => {
    const { action, next } = syncFromServer(state, step);
    state = next;
    return action;
  });
}

describe("服务端改动要不要盖掉画布", () => {
  it("别处改的就盖上去", () => {
    expect(run({ accounted: "W0", ours: [] }, [{ updatedAt: "W1", graphHash: "H1", dirty: false }])).toEqual(["apply"]);
  });

  it("自己刚存的不重建画布", () => {
    expect(run({ accounted: "W0", ours: ["H1"] }, [{ updatedAt: "W1", graphHash: "H1", dirty: false }])).toEqual([
      "accept-ours",
    ]);
  });

  it("画布还脏着就先不盖,而且不认 —— 存完之后它还要轮到", () => {
    expect(
      run({ accounted: "W0", ours: [] }, [
        { updatedAt: "W2", graphHash: "H2", dirty: true },
        { updatedAt: "W2", graphHash: "H2", dirty: false },
      ]),
    ).toEqual(["skip", "apply"]);
  });

  it("一次自动保存不该白重建一次画布", () => {
    // 这是那个 bug 的完整顺序。保存成功之后 setDirty(false) 会让 effect 先跑一遍,
    // 而那时**服务端那份还没回来**,props 上仍是旧的 W0;等重新拉取到了才变成 W1。
    // 此前的写法在保存成功时就把「已认过」乐观地写成了 W1,于是中间那一轮看到
    // 「W0 ≠ W1」,把它误读成"服务端又变了"—— 等真正的 W1 回来时画布白重建一次。
    expect(
      run({ accounted: "W0", ours: ["H1"] }, [
        { updatedAt: "W0", graphHash: "H0", dirty: false }, // setDirty(false) 引起的那一轮,props 还没更新
        { updatedAt: "W1", graphHash: "H1", dirty: false }, // 重新拉取回来了
      ]),
    ).toEqual(["skip", "accept-ours"]);
  });

  it("所以「已认过」这一格不能乐观地提前写", () => {
    // 同一串顺序,唯一的差别是保存成功时就把 accounted 写成了 W1(props 还没到 W1)。
    // 「已认过」的含义是**我们在 props 上见过的那一版**;写一个 props 还没到达的值,
    // 就等于把第一行那条早退给关了:还没更新的旧 props 被当成"服务端又变了"铺回画布。
    expect(
      run({ accounted: "W1", ours: ["H1"] }, [
        { updatedAt: "W0", graphHash: "H0", dirty: false },
        { updatedAt: "W1", graphHash: "H1", dirty: false },
      ]),
    ).toEqual(["apply", "apply"]);
  });

  it("自己刚存过,但先到的是智能体改的那一版:它不是我们的,盖上去", () => {
    //: 此前「我们刚存过」是一个布尔:下一版不管是谁的都当成自己的认下、不重建 —— 智能体经确认卡
    //: 改的图就这样被吞了,画布还是旧的。现在比的是图的摘要。
    expect(run({ accounted: "W0", ours: ["H1"] }, [{ updatedAt: "W2", graphHash: "H2", dirty: false }])).toEqual([
      "apply",
    ]);
  });

  it("连存两次、两版先后回来:都是自己的,都不重建", () => {
    expect(
      run({ accounted: "W0", ours: ["H1", "H2"] }, [
        { updatedAt: "W1", graphHash: "H1", dirty: false },
        { updatedAt: "W2", graphHash: "H2", dirty: false },
      ]),
    ).toEqual(["accept-ours", "accept-ours"]);
  });

  it("连存两次、只回来后一版:前一版不再等", () => {
    expect(
      run({ accounted: "W0", ours: ["H1", "H2"] }, [
        { updatedAt: "W2", graphHash: "H2", dirty: false },
        { updatedAt: "W3", graphHash: "H1", dirty: false },
      ]),
    ).toEqual(["accept-ours", "apply"]);
  });
});
