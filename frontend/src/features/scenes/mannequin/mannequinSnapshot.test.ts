/**
 * 快照取景:相机按人偶包围球紧框(框得紧 = 空白裁掉),横竖构图都顶到边但不裁肢体。
 * 纯 three 数学,node 里跑;真正的渲染路径(WebGLRenderer → toBlob)由
 * `mannequinSnapshot.dom.test.ts` 用 mock 渲染器钉。
 */
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { createMannequin, applyPose } from "./mannequinRig";
import { MANNEQUIN_POSES } from "./mannequinPoses";
import { frameMannequinCamera } from "./mannequinSnapshot";

const boxOf = (root: THREE.Object3D) => {
  root.updateMatrixWorld(true);
  return new THREE.Box3().setFromObject(root);
};

describe("frameMannequinCamera", () => {
  it("目标点是包围球心,方向是指定观察方向", () => {
    const box = new THREE.Box3(
      new THREE.Vector3(-1, 0, -1),
      new THREE.Vector3(1, 2, 1),
    );
    const frame = frameMannequinCamera(box, 1);
    expect(frame.target).toEqual([0, 1, 0]);
    const toCamera = new THREE.Vector3(...frame.position).sub(new THREE.Vector3(...frame.target));
    expect(toCamera.angleTo(new THREE.Vector3(0.45, 0.18, 1))).toBeLessThan(1e-6);
  });

  it("球刚好罩得住:任一方向的半径都顶不进视锥", () => {
    const rig = createMannequin();
    applyPose(rig, MANNEQUIN_POSES.armsUp!); // 举手把包围球撑大,最考验取景
    const box = boxOf(rig.root);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    for (const aspect of [1, 768 / 1024, 16 / 9]) {
      const frame = frameMannequinCamera(box, aspect, 38);
      const vHalf = THREE.MathUtils.degToRad(frame.fov) / 2;
      const hHalf = Math.atan(Math.tan(vHalf) * aspect);
      const distance = new THREE.Vector3(...frame.position).distanceTo(sphere.center);
      // 距离 × sin(紧的那半边半角) ≥ 半径:球在视锥里,且留了 1.08 边距。
      expect(distance * Math.sin(Math.min(vHalf, hHalf))).toBeGreaterThanOrEqual(sphere.radius);
      // 竖图时水平更紧:宽度方向顶边,距离比方形拉得更远。
      if (aspect < 1) {
        const square = frameMannequinCamera(box, 1, 38);
        const squareDistance = new THREE.Vector3(...square.position).distanceTo(sphere.center);
        expect(distance).toBeGreaterThan(squareDistance);
      }
    }
  });

  it("姿势变化 → 取景跟着变(快照框的是当前姿势)", () => {
    const rig = createMannequin();
    const standing = frameMannequinCamera(boxOf(rig.root), 1);
    applyPose(rig, MANNEQUIN_POSES.squat!);
    const squatting = frameMannequinCamera(boxOf(rig.root), 1);
    // 蹲比站矮、横向更宽 —— 取景目标(球心)和距离都不一样。
    expect(squatting.target[1]).toBeLessThan(standing.target[1]);
    expect(
      new THREE.Vector3(...squatting.position).distanceTo(new THREE.Vector3(...squatting.target),
      ),
    ).not.toBeCloseTo(
      new THREE.Vector3(...standing.position).distanceTo(new THREE.Vector3(...standing.target)),
    );
  });
});
