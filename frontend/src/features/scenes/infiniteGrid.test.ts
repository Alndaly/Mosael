/**
 * 地面网格没有边,而且**拉远之后还在**。
 *
 * 用户问的是「为何 3D 场景这个平面网格是有边界的,不像 Blender 那样没有边界」。答案是它此前
 * 就是一块写死 40 米的 `GridHelper` —— 到 ±20 米断出一条直边,而轨道控制允许拉到 1000 米。
 *
 * 好不好看只能用眼睛判断(这一版是在一个独立页面上逐个距离看过的),但**它是不是还在**、
 * **格距有没有换档**是数:固定淡出半径的写法在拉远时会让网格整个消失,而那正是"无限"要防的
 * 那件事。这里钉的是那几个数。
 */

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { createInfiniteGrid } from "./infiniteGrid";

function at(distance: number) {
  const grid = createInfiniteGrid();
  const camera = new THREE.PerspectiveCamera(45, 1.6, 0.05, 20000);
  camera.position.set(distance * 0.7, distance * 0.55, distance * 0.7);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld(true);
  grid.update(camera);
  const uniforms = (grid.object.material as THREE.ShaderMaterial).uniforms;
  return {
    grid,
    cell: uniforms.uCell.value as number,
    blend: uniforms.uBlend.value as number,
    fade: uniforms.uFade.value as number,
  };
}

describe("无限网格", () => {
  it("格距随相机距离往上换档", () => {
    // 固定格距的网格拉远之后是一片实心色,拉近又只剩几条线。
    const near = at(5).cell;
    const mid = at(50).cell;
    const far = at(500).cell;
    expect(near).toBeLessThan(mid);
    expect(mid).toBeLessThan(far);
    // 每档是十倍,和 Blender 一个习惯(1 / 10 / 100 米)。
    expect(mid / near).toBeCloseTo(10, 5);
    expect(far / mid).toBeCloseTo(10, 5);
  });

  it("换档是渐变,不是跳变", () => {
    // blend 在一档之内从 0 走到 1 —— 细档据此淡出。跳变的话,滚一下滚轮整张网格会闪一下。
    const blends = [8, 12, 18, 26, 40].map((d) => at(d).blend);
    for (const blend of blends) {
      expect(blend).toBeGreaterThanOrEqual(0);
      expect(blend).toBeLessThan(1);
    }
    expect(Math.max(...blends) - Math.min(...blends)).toBeGreaterThan(0.3);
  });

  it("淡出半径跟着相机距离走 —— 拉到几百米时网格还在", () => {
    // 这是「无限」的关键。固定半径(比如永远 60 米)的话,拉远一点整张网格就淡没了。
    const close = at(10);
    const far = at(400);
    expect(far.fade / close.fade).toBeCloseTo(40, 1);
    // 半径要罩得住相机看得到的那一片,否则画面里会出现一圈淡出的边 —— 那就是"有边界"。
    expect(close.fade).toBeGreaterThan(10 * 4);
    expect(far.fade).toBeGreaterThan(400 * 4);
  });

  it("承载面跟着相机的水平位置走,并且罩得住淡出半径", () => {
    const grid = createInfiniteGrid();
    const camera = new THREE.PerspectiveCamera(45, 1.6, 0.05, 20000);
    camera.position.set(137, 60, -249);
    camera.updateMatrixWorld(true);
    grid.update(camera);
    // 图案按世界坐标算,所以承载面跟着相机走不会让网格滑动;但它必须真的在相机脚下,
    // 否则拉远之后画面里看到的是这块面自己的边。
    expect(grid.object.position.x).toBeCloseTo(137, 5);
    expect(grid.object.position.z).toBeCloseTo(-249, 5);
    const uniforms = (grid.object.material as THREE.ShaderMaterial).uniforms;
    expect(grid.object.scale.x).toBeGreaterThan((uniforms.uFade.value as number) * 2);
  });

  it("贴到地面上时格距不会掉到毫米级", () => {
    // 相机贴地时距离趋近 0,按它直接取对数会让格距掉成 0.001 米 —— 那时整个屏幕是实心的。
    const camera = new THREE.PerspectiveCamera(45, 1.6, 0.05, 20000);
    camera.position.set(0, 0.02, 0.02);
    camera.updateMatrixWorld(true);
    const grid = createInfiniteGrid();
    grid.update(camera);
    const cell = (grid.object.material as THREE.ShaderMaterial).uniforms.uCell.value as number;
    expect(cell).toBeGreaterThanOrEqual(0.1);
  });

  it("不写深度,也不参与取景", () => {
    const grid = createInfiniteGrid();
    const material = grid.object.material as THREE.ShaderMaterial;
    // 写深度的话,网格下面的东西会被剔掉;参与取景的话,自动框选会把镜头拉到几公里外。
    expect(material.depthWrite).toBe(false);
    expect(material.transparent).toBe(true);
    expect(grid.object.frustumCulled).toBe(false);
  });
});
