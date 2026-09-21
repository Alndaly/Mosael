/**
 * 「场景中的物体」那份列表**是一棵树**。
 *
 * 用户报的是「场景中的物体缺少嵌套分组能力」。查下来数据层一直支持任意层数(`parent_id` +
 * 后端的环与深度校验),缺的全在这份列表:
 *
 * 1. **只有两级** —— 缩进写成 `paddingLeft: o.parent_id ? 24 : 10`,组里再放组和它的兄弟一样平;
 * 2. **顺序不对** —— 按 `objects` 数组原样画,而数组顺序不等于树的顺序。把一个物体移进某个组
 *    之后,那一行不会挪到组下面,只是原地多缩进一点,看上去像没生效。
 *
 * 这两条都看不出对错:画面上仍然是一列物体,只是"结构不太对"。所以拿数钉住。
 */

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { groupPath, initialScene, makeObject, objectTree } from "./sceneGraph";
import type { SceneContent, SceneObject } from "@/api/domains/scenes";

function scene(objects: SceneObject[]): SceneContent {
  return { ...initialScene(), objects };
}

/** 外组 →(内组 → 盒子)+ 球;另有一个顶层的地面。**故意打乱数组顺序**。 */
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

describe("物体列表是一棵树", () => {
  it("父在前,后代紧跟其后 —— 不管数组里怎么排", () => {
    const { content, ids } = nested();
    const order = objectTree(content).map((row) => row.object.id);
    expect(order.indexOf(ids.outer)).toBeLessThan(order.indexOf(ids.inner));
    expect(order.indexOf(ids.inner)).toBeLessThan(order.indexOf(ids.box));
    // 内组那一支要连着走完,再轮到外组的下一个孩子。
    expect(order.indexOf(ids.box)).toBeLessThan(order.indexOf(ids.ball));
  });

  it("层数是真的层数,不是「有没有父级」", () => {
    const { content, ids } = nested();
    const depth = Object.fromEntries(
      objectTree(content).map((row) => [row.object.id, row.depth]),
    );
    expect(depth[ids.outer]).toBe(0);
    expect(depth[ids.inner]).toBe(1);
    // 这一条正是此前做不到的:三层的东西和两层的画在同一个缩进上。
    expect(depth[ids.box]).toBe(2);
    expect(depth[ids.floor]).toBe(0);
  });

  it("每行知道自己下面直接挂着几个 —— 没孩子就不该有折叠箭头", () => {
    const { content, ids } = nested();
    const children = Object.fromEntries(
      objectTree(content).map((row) => [row.object.id, row.children]),
    );
    expect(children[ids.outer]).toBe(2);
    expect(children[ids.inner]).toBe(1);
    expect(children[ids.box]).toBe(0);
  });

  it("收起来的组,后代整片跳过,但它自己还在", () => {
    const { content, ids } = nested();
    const ids2 = objectTree(content, new Set([ids.inner])).map((row) => row.object.id);
    expect(ids2).toContain(ids.inner);
    expect(ids2).not.toContain(ids.box);
    // 兄弟不受影响 —— 收的是这一支,不是整棵。
    expect(ids2).toContain(ids.ball);
  });

  it("父级已经不在了的孤儿画在顶层,而不是藏起来", () => {
    // 后端拒得了环,但一份手工改过的场景仍可能指着一个已经删掉的组。那时藏起来最糟:
    // 用户会以为物体丢了,而它其实还在数据里。
    const orphan = makeObject("box", { name: "孤儿", parent_id: "没有这个组" });
    const rows = objectTree(scene([orphan]));
    expect(rows).toHaveLength(1);
    expect(rows[0].depth).toBe(0);
  });

  it("数据里有环也不把界面挂掉", () => {
    const a = makeObject("group", { name: "甲" });
    const b = makeObject("group", { name: "乙", parent_id: a.id });
    const looped = scene([{ ...a, parent_id: b.id }, b]);
    // 两个都指着对方,谁都不是顶层 —— 不能因此死循环,也不能因此一行都不画。
    expect(() => objectTree(looped)).not.toThrow();
  });

  it("每个物体只出现一次", () => {
    const { content } = nested();
    const rows = objectTree(content);
    expect(new Set(rows.map((row) => row.object.id)).size).toBe(rows.length);
    expect(rows).toHaveLength(content.objects.length);
  });
});

describe("「所属组」下拉带上上级", () => {
  it("嵌套的组显示成一条路径", () => {
    const { content, ids } = nested();
    expect(groupPath(content, ids.inner)).toBe("外组 / 内组");
    expect(groupPath(content, ids.outer)).toBe("外组");
  });

  it("「添加 → 组」建出来的都叫「组」—— 不带上级就全靠猜", () => {
    const outer = makeObject("group", { name: "组" });
    const inner = makeObject("group", { name: "组", parent_id: outer.id });
    const content = scene([outer, inner]);
    expect(groupPath(content, outer.id)).not.toBe(groupPath(content, inner.id));
  });
});

describe("折叠箭头落在面板内距里,名字不会被它顶右一格", () => {
  const css = readFileSync(new URL("./scenes.css", import.meta.url), "utf8");
  const rule = (selector: string) => {
    const at = css.indexOf(`${selector} {`);
    expect(at, `样式表里找不到 ${selector}`).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf("}", at));
  };

  it("整列往左推满一个箭头宽 —— 不推的话是凭空多出来的一格缩进", () => {
    // 加箭头之前:列表 -8px、按钮内距 8px,于是图标正好落在标题那条竖线上。
    // 加了 16px 的箭头之后如果不推,整列会整体右移 16px。
    expect(rule(".scene-panel-body > .scene-object-list")).toContain(
      "margin-inline: calc(var(--scene-twist-width) * -1)",
    );
    expect(rule(".scene-object-list")).toContain("--scene-twist-width: 16px");
  });

  it("箭头已经占了那一格,名字按钮就不再补左内距 —— 补了是双份", () => {
    expect(rule(".scene-object-row > .scene-object-twist + button")).toContain("padding-left: 0");
  });

  it("没孩子的行也占同宽的一格,名字才不会随「有没有孩子」左右跳", () => {
    expect(rule(".scene-object-twist")).toContain("width: var(--scene-twist-width)");
  });
});
