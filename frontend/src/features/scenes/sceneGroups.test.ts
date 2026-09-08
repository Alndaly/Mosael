/**
 * 「移到某个组」。
 *
 * 这是「组」此前缺的那一半:数据模型一直支持 `parent_id`、后端也有完整的环与深度校验,
 * 但界面上没有任何入口能把已有的物体放进已有的组 —— 于是「添加 → 组」建出来的空组是个
 * 建完就废的空盒子。
 *
 * 钉的重点是**不能形成环**:把一个组移进它自己的后代,后端会拒(`valid_hierarchy`),但那时
 * 用户已经点下去了,而且拒的方式是整次保存失败 —— 前端必须先挡住。
 */
import { describe, expect, it } from "vitest";

import { groupTargets, initialScene, makeObject, moveToGroup } from "./sceneGraph";
import type { SceneContent } from "@/api/domains/scenes";

/** 外组 → 内组 → 盒子 的三层结构。 */
function nested(): { content: SceneContent; outer: string; inner: string; box: string } {
  const outer = makeObject("group", { name: "外组" });
  const inner = makeObject("group", { name: "内组", parent_id: outer.id });
  const box = makeObject("box", { name: "盒子", parent_id: inner.id });
  const content = { ...initialScene(), objects: [outer, inner, box] };
  return { content, outer: outer.id, inner: inner.id, box: box.id };
}

const parentOf = (content: SceneContent, id: string) =>
  content.objects.find((o) => o.id === id)?.parent_id ?? null;

describe("移到某个组", () => {
  it("把物体放进组,以及移回顶层", () => {
    const { content, outer, box } = nested();
    expect(parentOf(moveToGroup(content, box, outer), box)).toBe(outer);
    expect(parentOf(moveToGroup(content, box, null), box)).toBeNull();
  });

  it("不能移进自己的后代 —— 那会形成一个环", () => {
    // 外组移进内组:内组是外组的孩子,这一步会让两者互为祖先。后端 valid_hierarchy 会拒,
    // 而那时整次保存都失败了 —— 所以这里就要挡住。
    const { content, outer, inner } = nested();
    expect(moveToGroup(content, outer, inner)).toBe(content);
  });

  it("不能移进自己", () => {
    const { content, box } = nested();
    expect(moveToGroup(content, box, box)).toBe(content);
  });

  it("只有组能装东西", () => {
    // 盒子不是组。后端那条规则是「Only groups may contain objects」。
    const { content, box, outer } = nested();
    const another = makeObject("sphere");
    const withSphere = { ...content, objects: [...content.objects, another] };
    expect(moveToGroup(withSphere, another.id, box)).toBe(withSphere);
    expect(parentOf(moveToGroup(withSphere, another.id, outer), another.id)).toBe(outer);
  });

  it("已经在那个组里就原样返回 —— 不产生一次空的撤销步", () => {
    const { content, inner, box } = nested();
    expect(moveToGroup(content, box, inner)).toBe(content);
  });
});

describe("可以移进去的组", () => {
  it("排除自己和自己的后代", () => {
    const { content, outer, inner, box } = nested();
    expect(groupTargets(content, box).map((g) => g.id).sort()).toEqual([outer, inner].sort());
    expect(groupTargets(content, outer)).toEqual([]);   // 只有它自己和它的后代是组
    expect(groupTargets(content, inner).map((g) => g.id)).toEqual([outer]);
  });
});
