/**
 * 在「场景中的物体」列表里拖一个物体:落在哪一行、落在一行的哪一段,以及落完之后的数组。
 *
 * 这一层是纯数据(不碰 DOM、不碰 dnd-kit):指针拖拽和 ⌥↑/⌥↓ 都收敛到 `moveObject`,
 * 所以环、深度、"只有组能装"这三条只在这里判一次。
 */

import { describe, expect, it } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import type { SceneContent, SceneObject } from "@/api/domains/scenes";

import { canDrop, dropZoneFor, moveObject, ROOT_DROP_ID, siblingsOf } from "./sceneDrag";
import { initialScene, makeObject, objectTree } from "./sceneGraph";

const zh = (key: MessageKey) => messages["zh-CN"][key];

function scene(objects: SceneObject[]): SceneContent {
  return { ...initialScene(zh), objects };
}

/** 外组 →(内组 → 盒子)+ 球;另有一个顶层的地面。**故意打乱数组顺序**(和 objectTree.test.ts 同一份)。 */
function nested() {
  const outer = makeObject("group", { name: "外组" });
  const inner = makeObject("group", { name: "内组", parent_id: outer.id });
  const box = makeObject("box", { name: "盒子", parent_id: inner.id });
  const ball = makeObject("sphere", { name: "球", parent_id: outer.id });
  const floor = makeObject("plane", { name: "地面" });
  return {
    content: scene([box, floor, inner, ball, outer]),
    ids: { outer: outer.id, inner: inner.id, box: box.id, ball: ball.id, floor: floor.id },
  };
}

const order = (content: SceneContent) => objectTree(content).map((row) => row.object.name);
const parentOf = (content: SceneContent, id: string) =>
  content.objects.find((one) => one.id === id)?.parent_id ?? null;

describe("落在这一行的哪一段", () => {
  const row = { top: 100, height: 30 };

  it("上三成 / 下三成是「排在它前面 / 后面」", () => {
    expect(dropZoneFor(100, row.top, row.height, false)).toBe("before");
    expect(dropZoneFor(129, row.top, row.height, false)).toBe("after");
    // 边界是"到了就算":8px(上三成)进中段,22px(下三成)也进中段。
    expect(dropZoneFor(101, row.top, row.height, false)).toBe("before");
    expect(dropZoneFor(128, row.top, row.height, false)).toBe("after");
  });

  it("中间四成:是组就是「放进去」", () => {
    expect(dropZoneFor(115, row.top, row.height, true)).toBe("inside");
  });

  it("中间四成落在非组上:按上下半分,仍然是排序 —— 非组没有「放进去」这一段", () => {
    expect(dropZoneFor(112, row.top, row.height, false)).toBe("before");
    expect(dropZoneFor(118, row.top, row.height, false)).toBe("after");
    expect(dropZoneFor(115, row.top, row.height, false)).toBe("after");
  });

  it("量不到高度时不乱猜:组按放进去,别的按排在后面", () => {
    expect(dropZoneFor(0, 0, 0, true)).toBe("inside");
    expect(dropZoneFor(0, 0, 0, false)).toBe("after");
  });
});

describe("拖动改的是数组顺序和那一个 parent_id", () => {
  it("同级里排到前面:数组序变了,父级没动,树里的先后跟着变", () => {
    const { content, ids } = nested();
    // 数组是打乱的,树按父级分桶之后才是这样:根层的地面排在前面。
    expect(order(content)).toEqual(["地面", "外组", "内组", "盒子", "球"]);

    const next = moveObject(content, ids.ball, ids.inner, "before")!;
    expect(next).not.toBeNull();
    expect(parentOf(next, ids.ball)).toBe(ids.outer);
    expect(order(next)).toEqual(["地面", "外组", "球", "内组", "盒子"]);
    // 原来的那一份没被就地改掉(撤销栈里存的是它)。
    expect(order(content)).toEqual(["地面", "外组", "内组", "盒子", "球"]);
  });

  it("同级里排到后面:插在目标行的后一位", () => {
    const { content, ids } = nested();
    const next = moveObject(content, ids.inner, ids.ball, "after")!;
    expect(order(next)).toEqual(["地面", "外组", "球", "内组", "盒子"]);
  });

  it("拖进组:parent_id 换成那个组,排在它那一桶的末尾", () => {
    const { content, ids } = nested();
    const next = moveObject(content, ids.floor, ids.outer, "inside")!;
    expect(parentOf(next, ids.floor)).toBe(ids.outer);
    // 外组的桶里原本是 [内组, 球],所以地面接在球后面。
    expect(order(next)).toEqual(["外组", "内组", "盒子", "球", "地面"]);
    expect(next.objects.filter((one) => parentOf(next, one.id) === ids.outer).map((one) => one.name)).toEqual([
      "内组",
      "球",
      "地面",
    ]);
  });

  it("拖进空的组:紧跟在那个组后面", () => {
    const { content, ids } = nested();
    const empty = makeObject("group", { name: "空组" });
    const withEmpty = scene([...content.objects, empty]);
    const next = moveObject(withEmpty, ids.floor, empty.id, "inside")!;
    expect(parentOf(next, ids.floor)).toBe(empty.id);
    expect(order(next)).toEqual(["外组", "内组", "盒子", "球", "空组", "地面"]);
  });

  it("拖出组:落在根层某一行上,parent_id 回到 null", () => {
    const { content, ids } = nested();
    const next = moveObject(content, ids.box, ids.floor, "before")!;
    expect(parentOf(next, ids.box)).toBeNull();
    // 盒子排在地面前面 —— 它原来挂在内组下,那一位只改了它自己。
    expect(order(next)).toEqual(["盒子", "地面", "外组", "内组", "球"]);
  });

  it("拖到列表末尾那条空白:回到最外层,接在根层最后", () => {
    const { content, ids } = nested();
    const next = moveObject(content, ids.box, ROOT_DROP_ID, "after")!;
    expect(parentOf(next, ids.box)).toBeNull();
    expect(order(next)).toEqual(["地面", "外组", "内组", "球", "盒子"]);
  });

  it("把组拖进另一个组:整支跟着走", () => {
    const { content, ids } = nested();
    const other = makeObject("group", { name: "新组" });
    const next = moveObject(scene([...content.objects, other]), ids.inner, other.id, "inside")!;
    expect(parentOf(next, ids.inner)).toBe(other.id);
    // 内组的孩子仍然在它下面 —— 只改了内组那一位。
    expect(parentOf(next, ids.box)).toBe(ids.inner);
    expect(order(next)).toEqual(["地面", "外组", "球", "新组", "内组", "盒子"]);
  });
});

describe("落不下去的地方", () => {
  it("拖进非 group:拒绝(后端只有组能当父级)", () => {
    const { content, ids } = nested();
    expect(moveObject(content, ids.floor, ids.ball, "inside")).toBeNull();
    expect(canDrop(content, ids.floor, ids.ball, "inside")).toBe(false);
  });

  it("拖进自己的后代:拒绝(成环)", () => {
    const { content, ids } = nested();
    expect(moveObject(content, ids.outer, ids.inner, "inside")).toBeNull();
    expect(moveObject(content, ids.outer, ids.box, "inside")).toBeNull();
    // 排在子孙前后也不行:那一步要把它挂到子孙的父级下,而当下的父级链里有它自己。
    expect(moveObject(content, ids.outer, ids.box, "before")).toBeNull();
  });

  it("拖到自己身上 / 拖到不存在的行:拒绝", () => {
    const { content, ids } = nested();
    expect(moveObject(content, ids.ball, ids.ball, "inside")).toBeNull();
    expect(moveObject(content, ids.ball, "没有这一行", "after")).toBeNull();
    expect(moveObject(content, "没有这个物体", ids.ball, "after")).toBeNull();
  });

  it("原地松手不算一步:返回 null,别往撤销栈里塞空记录", () => {
    const { content, ids } = nested();
    expect(moveObject(content, ids.ball, ids.inner, "after")).toBeNull();
    // 已经在根层末尾的,拖到末尾那条空白上也没有变化。
    expect(moveObject(content, ids.outer, ROOT_DROP_ID, "after")).toBeNull();
  });

  it("深到后端会拒的那一层就落不下(一条链最多 16 个)", () => {
    // g0 → g1 → … → g15:g15 在第 15 层,正好是上限。
    const chain: SceneObject[] = [];
    for (let level = 0; level < 16; level += 1) {
      chain.push(
        makeObject("group", {
          name: `第 ${level} 层`,
          parent_id: level ? chain[level - 1]!.id : null,
        }),
      );
    }
    const solo = makeObject("group", { name: "单人组" });
    const child = makeObject("box", { name: "里面的盒子", parent_id: solo.id });
    const content = scene([...chain, solo, child]);

    // 单人组自己占一层、里面还有个盒子:15 + 1 + 1 = 17,超过 16。
    expect(moveObject(content, solo.id, chain[15]!.id, "inside")).toBeNull();
    // 排在它后面也是同一个父级链:14 + 1 + 1 = 16,同样超。
    expect(moveObject(content, solo.id, chain[15]!.id, "after")).toBeNull();
    // 浅一层就放得下:12 + 1 + 1 = 14(放进去),或者 13 + 1 = 14(排在后面)。
    expect(moveObject(content, solo.id, chain[12]!.id, "inside")).not.toBeNull();
    expect(moveObject(content, solo.id, chain[12]!.id, "after")).not.toBeNull();
  });

  it("父级已经不在了的孤儿:按根层算,能拖得动", () => {
    const orphan = makeObject("box", { name: "孤儿", parent_id: "没有这个组" });
    const floor = makeObject("plane", { name: "地面" });
    const group = makeObject("group", { name: "组" });
    const content = scene([orphan, floor, group]);
    const next = moveObject(content, orphan.id, group.id, "inside")!;
    expect(parentOf(next, orphan.id)).toBe(group.id);
  });
});

describe("同级的先后(键盘的 ⌥↑ / ⌥↓ 用它找邻居)", () => {
  it("同一个父级的按数组序,含它自己", () => {
    const { content, ids } = nested();
    expect(siblingsOf(content, ids.ball).map((one) => one.name)).toEqual(["内组", "球"]);
    expect(siblingsOf(content, ids.floor).map((one) => one.name)).toEqual(["地面", "外组"]);
    expect(siblingsOf(content, ids.box).map((one) => one.name)).toEqual(["盒子"]);
    expect(siblingsOf(content, "没有这个物体")).toEqual([]);
  });
});
