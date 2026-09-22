/**
 * 共享常量契约的**前端一侧**:跑 contracts/shared-constants.json。
 *
 * 这份契约钉的 56px 有四处实现,其中**两处是前端文件** —— 而跑它的一直只有
 * `backend/tests/test_shared_constants_parity.py`(用正则去读这两个 TS 文件)。
 *
 * 前端有八份 `*.parity.test.ts`,唯独这一份没有前端侧的跑手。而一次只改前端的提交,
 * 按仓库习惯跑的是 `pnpm lint` 和前端 vitest —— **这条契约在那一刻不会被触发**。
 * 改这个数的人最可能待的地方,恰恰是没人看着的地方。
 *
 * 不一致的后果:Electron 按它定内嵌发布视图的边界,前端按它定那条工具栏的高度。两者不等
 * 就露出一条缝,缝里是 App 自己的顶栏 —— 看着像画面穿帮,而不像一个 bug,所以很容易被
 * 当成本来就长这样。
 *
 * 这里**不重抄一遍 56**:值从契约里读,前端的两个常量跟它比。抄一遍的话,两边一起错时
 * 这条测试是绿的。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../contracts/shared-constants.json";
import { WINDOW_CHROME_HEIGHT } from "@/lib/windowChrome";
import { PUBLISH_BAR_HEIGHT } from "@/app/App";

type Constant = (typeof contract)["constants"][number];

function constantNamed(name: string): Constant {
  const found = contract.constants.find((one) => one.name === name);
  if (!found) throw new Error(`契约里没有 ${name} —— 它被删了还是改名了?`);
  return found;
}

describe("shared-constants 的前端一侧", () => {
  it("内嵌视图顶栏高度:前端的两个常量都等于契约值", () => {
    const expected = constantNamed("embed_header_height_px").value;

    expect(PUBLISH_BAR_HEIGHT).toBe(expected);
    expect(WINDOW_CHROME_HEIGHT).toBe(expected);
  });

  it("契约点名的前端实现位置都还在", () => {
    // 契约记着每个常量在哪个文件、叫什么名字。位置过期了,后端那条正则就读不到它 ——
    // 而"读不到"和"值对不上"在那边是同一种红,这里先把前者挡掉。
    const declared = constantNamed("embed_header_height_px").implementations
      .filter((one) => one.runtime === "frontend")
      .map((one) => `${one.location}:${one.symbol}`);

    expect(declared).toContain("frontend/src/app/App.tsx:PUBLISH_BAR_HEIGHT");
    expect(declared).toContain("frontend/src/lib/windowChrome.ts:WINDOW_CHROME_HEIGHT");
  });
});
