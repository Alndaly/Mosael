/**
 * 姿势预设:角度表本身合法(关节名认得、角度有限且在 ±180°),顺序表和预设表对得上,
 * 应用预设真的把关节转过去、复位真的归零。
 */
import { describe, expect, it } from "vitest";

import {
  applyPose,
  createMannequin,
  MANNEQUIN_JOINTS,
  readPose,
  resetPose,
} from "./mannequinRig";
import { MANNEQUIN_POSES, MANNEQUIN_POSE_ORDER, poseIsValid } from "./mannequinPoses";

describe("姿势预设表", () => {
  it("每张预设都合法:认得的关节、有限数、±180° 内", () => {
    for (const [name, pose] of Object.entries(MANNEQUIN_POSES)) {
      expect(poseIsValid(pose, MANNEQUIN_JOINTS), `预设 ${name} 含非法关节或角度`).toBe(true);
      if (pose.hipsDrop !== undefined) {
        expect(pose.hipsDrop).toBeGreaterThan(0);
        expect(pose.hipsDrop).toBeLessThan(0.95); // 不能沉到地底下去
      }
    }
  });

  it("顺序表覆盖全部预设,不多不少", () => {
    expect([...MANNEQUIN_POSE_ORDER].sort()).toEqual(Object.keys(MANNEQUIN_POSES).sort());
  });

  it("要求的几个动作都在:站 / 走 / 坐 / 蹲 / 举手", () => {
    for (const key of ["stand", "walk", "sit", "squat", "armsUp"])
      expect(MANNEQUIN_POSES[key]).toBeDefined();
  });
});

describe("应用预设", () => {
  it("坐:大腿前放、小腿收回,髋落到椅子高,读数与表一致", () => {
    const rig = createMannequin();
    resetPose(rig);
    applyPose(rig, MANNEQUIN_POSES.sit!);
    const pose = readPose(rig);
    expect(pose.thighL).toEqual(MANNEQUIN_POSES.sit!.angles.thighL!);
    expect(pose.thighL![0]).toBeLessThan(-80); // 大腿接近水平前放
    expect(pose.shinL![0]).toBeGreaterThan(80); // 膝盖收回
    expect(rig.joints.get("hips")!.position.y).toBeLessThan(0.6);
  });

  it("举手:两臂上抬,左正右负(对称)", () => {
    const rig = createMannequin();
    applyPose(rig, MANNEQUIN_POSES.armsUp!);
    const pose = readPose(rig);
    expect(Math.abs(pose.upperArmL![2])).toBeGreaterThan(120);
    expect(pose.upperArmL![2]).toBe(-pose.upperArmR![2]);
    // 举手不挪髋。
    expect(rig.joints.get("hips")!.position.y).toBeCloseTo(0.95);
  });

  it("预设之间不互相渗漏:换预设前复位", () => {
    // squat 的膝屈角(102°)比 sit(86°)大 —— 先蹲后坐,shinL 必须是坐的值。
    const rig = createMannequin();
    applyPose(rig, MANNEQUIN_POSES.squat!);
    resetPose(rig);
    applyPose(rig, MANNEQUIN_POSES.sit!);
    expect(readPose(rig).shinL).toEqual(MANNEQUIN_POSES.sit!.angles.shinL!);
  });
});
