/**
 * 场景里的 figure 是关节人形:复用 mannequinRig 的 19 关节层级 + FK,默认直立,带 pose 就按它转。
 * 预设 → 场景 pose → 人偶姿势表 的序列化 round-trip(蛇形 hips_drop)。全是不碰 WebGL 的 three 数学。
 */
import { describe, expect, it } from "vitest";

import { MANNEQUIN_JOINTS, poseFromMannequin, poseToMannequin, readPose, type MannequinRig } from "./mannequin/mannequinRig";
import { MANNEQUIN_POSES } from "./mannequin/mannequinPoses";
import { makeObject } from "./sceneGraph";
import { geometryObject } from "./sceneMeshes";
import type { SceneObject } from "@/api/domains/scenes";

function rigOf(object: SceneObject): MannequinRig {
  const rig = geometryObject(object).userData.figureRig as MannequinRig | undefined;
  expect(rig).toBeTruthy();
  return rig!;
}

describe("场景里的 figure 是关节人形", () => {
  it("figure 由 19 关节层级拼成,默认直立", () => {
    const rig = rigOf(makeObject("figure"));
    expect(rig.joints.size).toBe(MANNEQUIN_JOINTS.length);
    expect(rig.meshes.length).toBe(19);
    for (const name of MANNEQUIN_JOINTS) expect(readPose(rig)[name]).toEqual([0, 0, 0]);
  });

  it("figure 带上 pose 就按它转关节(复用同一套 FK)", () => {
    const rig = rigOf(makeObject("figure", { pose: poseFromMannequin(MANNEQUIN_POSES.armsUp!) }));
    const pose = readPose(rig);
    expect(pose.upperArmL![2]).toBeCloseTo(152, 5);
    expect(pose.upperArmR![2]).toBeCloseTo(-152, 5);
  });

  it("预设 → 场景 pose → 人偶姿势表 round-trip(蛇形 hips_drop)", () => {
    const preset = MANNEQUIN_POSES.sit!;
    const scenePose = poseFromMannequin(preset);
    expect(scenePose.hips_drop).toBe(0.44);
    expect(poseToMannequin(scenePose)).toEqual({ angles: preset.angles, hipsDrop: 0.44 });
  });
});
