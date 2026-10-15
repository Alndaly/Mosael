/**
 * 人偶骨架:层级对不对(每个关节一个 pivot、父子按约定)、FK 转起来子层级跟不跟、
 * 拾取认不认得关节。全是不碰 WebGL 的 three 数学 —— node 里直接跑。
 */
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import {
  applyPose,
  createMannequin,
  MANNEQUIN_HEIGHT,
  MANNEQUIN_JOINTS,
  poseFromMannequin,
  poseToMannequin,
  readPose,
  resetPose,
} from "./mannequinRig";

function rig() {
  const r = createMannequin();
  r.root.updateMatrixWorld(true);
  return r;
}

describe("人偶层级", () => {
  it("每个关节一个 pivot,数量钉死", () => {
    const r = rig();
    expect(r.joints.size).toBe(MANNEQUIN_JOINTS.length);
    expect(MANNEQUIN_JOINTS.length).toBe(19);
    for (const name of MANNEQUIN_JOINTS) expect(r.joints.has(name)).toBe(true);
  });

  it("中轴:髋 → 脊柱 → 胸 → 颈 → 头", () => {
    const r = rig();
    const parentOf = (name: string) => r.joints.get(name as never)!.parent;
    expect(parentOf("spine")).toBe(r.joints.get("hips"));
    expect(parentOf("chest")).toBe(r.joints.get("spine"));
    expect(parentOf("neck")).toBe(r.joints.get("chest"));
    expect(parentOf("head")).toBe(r.joints.get("neck"));
  });

  it("四肢:胸 → 肩 → 上臂 → 前臂 → 手;髋 → 大腿 → 小腿 → 脚", () => {
    const r = rig();
    for (const side of ["L", "R"] as const) {
      const at = (n: string) => r.joints.get(`${n}${side}` as never)!;
      expect(at("shoulder").parent).toBe(r.joints.get("chest"));
      expect(at("upperArm").parent).toBe(at("shoulder"));
      expect(at("forearm").parent).toBe(at("upperArm"));
      expect(at("hand").parent).toBe(at("forearm"));
      expect(at("thigh").parent).toBe(r.joints.get("hips"));
      expect(at("shin").parent).toBe(at("thigh"));
      expect(at("foot").parent).toBe(at("shin"));
    }
  });

  it("脚底落在 y≈0,头顶接近身高(比例没散)", () => {
    const r = rig();
    const box = new THREE.Box3().setFromObject(r.root);
    expect(box.min.y).toBeGreaterThan(-0.01);
    expect(box.min.y).toBeLessThan(0.05);
    expect(box.max.y).toBeGreaterThan(MANNEQUIN_HEIGHT * 0.95);
    expect(box.max.y).toBeLessThan(MANNEQUIN_HEIGHT * 1.1);
  });

  it("共享一份哑光材质,网格数有上限(性能)", () => {
    const r = rig();
    expect(r.material.roughness).toBeGreaterThan(0.5);
    for (const mesh of r.meshes) expect(mesh.material).toBe(r.material);
    expect(r.meshes.length).toBeLessThanOrEqual(24);
  });
});

describe("FK:转父关节,子层级跟随", () => {
  it("转肩 → 整条手臂跟着走", () => {
    const r = rig();
    const before = new THREE.Vector3();
    r.joints.get("handL")!.getWorldPosition(before);
    // 左臂绕 Z 转 90°:从下垂(-Y)抬到 +X 外侧。
    r.joints.get("upperArmL")!.rotation.z = Math.PI / 2;
    r.root.updateMatrixWorld(true);
    const after = new THREE.Vector3();
    r.joints.get("handL")!.getWorldPosition(after);
    expect(after.distanceTo(before)).toBeGreaterThan(0.2);
    // 手真的被抬到肩膀高度附近(而不是只在原地转)。
    expect(Math.abs(after.y - r.joints.get("upperArmL")!.getWorldPosition(new THREE.Vector3()).y)).toBeLessThan(0.05);
  });

  it("转髋 → 全身跟着转:甩出去的手挪位,各处高度不变", () => {
    const r = rig();
    const handBefore = new THREE.Vector3(),
      headBefore = new THREE.Vector3(),
      footBefore = new THREE.Vector3();
    r.joints.get("handL")!.getWorldPosition(handBefore);
    r.joints.get("head")!.getWorldPosition(headBefore);
    r.joints.get("footL")!.getWorldPosition(footBefore);
    r.joints.get("hips")!.rotation.y = Math.PI / 2;
    r.root.updateMatrixWorld(true);
    const handAfter = new THREE.Vector3(),
      headAfter = new THREE.Vector3(),
      footAfter = new THREE.Vector3();
    r.joints.get("handL")!.getWorldPosition(handAfter);
    r.joints.get("head")!.getWorldPosition(headAfter);
    r.joints.get("footL")!.getWorldPosition(footAfter);
    // 手垂在身侧(离竖直轴 ~0.2 米),身体绕髋转 90° 它被甩出去一大步。
    expect(handAfter.distanceTo(handBefore)).toBeGreaterThan(0.2);
    // 竖直轴上的旋转不改任何高度:头、脚原地等高。
    expect(Math.abs(headAfter.y - headBefore.y)).toBeLessThan(1e-6);
    expect(Math.abs(footAfter.y - footBefore.y)).toBeLessThan(1e-6);
    // 脚跟着转:它到髋轴的水平距离不变(刚体跟随,不是被丢下)。
    const flat = (v: THREE.Vector3) => Math.hypot(v.x, v.z);
    expect(Math.abs(flat(footAfter) - flat(footBefore))).toBeLessThan(1e-6);
  });

  it("拾取:命中的 limb mesh 认得出属于哪个关节", () => {
    const r = rig();
    const forearmMesh = r.meshes.find(
      (m) => m.userData.mannequinJoint === "forearmR",
    )!;
    expect(r.jointOf(forearmMesh)).toBe("forearmR");
    expect(r.jointOf(forearmMesh.children[0] ?? null) ?? r.jointOf(forearmMesh)).toBeTruthy();
    // 人偶以外的对象不认。
    expect(r.jointOf(new THREE.Group())).toBeNull();
    expect(r.jointOf(null)).toBeNull();
  });
});

describe("姿势读写", () => {
  it("applyPose → readPose 原样读回(度)", () => {
    const r = rig();
    applyPose(r, { angles: { upperArmL: [0, 0, 45], thighR: [-30, 0, 0] } });
    const pose = readPose(r);
    expect(pose.upperArmL).toEqual([0, 0, 45]);
    expect(pose.thighR).toEqual([-30, 0, 0]);
    expect(pose.head).toEqual([0, 0, 0]);
  });

  it("不认识的关节名静悄悄跳过(姿势表 forward-compatible)", () => {
    const r = rig();
    applyPose(r, { angles: { notAJoint: [1, 2, 3] } as never });
    expect(readPose(r).hips).toEqual([0, 0, 0]);
  });

  it("resetPose 把所有关节归零、髋回到站姿高度", () => {
    const r = rig();
    const standingHipY = r.joints.get("hips")!.position.y;
    applyPose(r, {
      hipsDrop: 0.44,
      angles: { hips: [10, 20, 0], head: [-15, 0, 5], shinL: [40, 0, 0] },
    });
    expect(r.joints.get("hips")!.position.y).toBeCloseTo(standingHipY - 0.44);
    resetPose(r);
    for (const name of MANNEQUIN_JOINTS)
      expect(readPose(r)[name]).toEqual([0, 0, 0]);
    expect(r.joints.get("hips")!.position.y).toBeCloseTo(standingHipY);
  });
});

describe("pose ↔ 场景对象序列化", () => {
  it("poseFromMannequin 用蛇形 hips_drop,poseToMannequin 读回来", () => {
    const scenePose = poseFromMannequin({
      angles: { upperArmL: [0, 0, 152], thighR: [-30, 0, 0] },
      hipsDrop: 0.44,
    });
    expect(scenePose).toEqual({
      angles: { upperArmL: [0, 0, 152], thighR: [-30, 0, 0] },
      hips_drop: 0.44,
    });
    expect(poseToMannequin(scenePose)).toEqual({
      angles: { upperArmL: [0, 0, 152], thighR: [-30, 0, 0] },
      hipsDrop: 0.44,
    });
  });

  it("髋没下沉就不写 hips_drop,读回来是 0", () => {
    const scenePose = poseFromMannequin({ angles: { head: [-8, 0, 0] } });
    expect(scenePose.hips_drop).toBeUndefined();
    expect(poseToMannequin(scenePose).hipsDrop).toBe(0);
  });

  it("没有 pose(undefined/null)就是直立默认", () => {
    expect(poseToMannequin(null)).toEqual({ angles: {}, hipsDrop: 0 });
    expect(poseToMannequin(undefined)).toEqual({ angles: {}, hipsDrop: 0 });
  });
});
