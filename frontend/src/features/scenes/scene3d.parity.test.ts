import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import * as THREE from "three";
import { describe, expect, it } from "vitest";

import type { SceneObject, SceneShot } from "@/api/domains/scenes";
import { kelvinRgb, sunDirection } from "./lighting";
import { sampleCamera, sampleObject } from "./sceneGraph";
import { geometryObject } from "./sceneMeshes";

/**
 * The frontend half of the 3D scene contract: runs contracts/scene-3d-cases.json, the SAME file the
 * backend's tests/test_scene_3d_parity.py runs.
 *
 * The workbench edits the scene interactively in three.js; the backend renders the same scene
 * headless (blockout reference frames and camera-move videos) and writes it out as the GLB sent to
 * Blender. Three consumers, two languages, one geometry — how tall the figure is, how thick a wall
 * is, whether a sphere stands on the floor, how a camera move eases. This used to be held together
 * by a comment at the top of meshes.py, which stops nothing: change one side and the reference
 * frames, the finished video and the Blender scene quietly disagree, with every test still green.
 *
 * Change the semantics in the corpus FIRST, watch both sides go red, then fix both.
 */
const CONTRACT_PATH = fileURLToPath(new URL("../../../../contracts/scene-3d-cases.json", import.meta.url));

type Vec3 = [number, number, number];
type GeometryCase = {
  name: string;
  why: string;
  object: { kind: string; parameters: Record<string, number> };
  parts: number;
  min: Vec3;
  max: Vec3;
};
type AidCase = { name: string; why: string; object: { kind: string }; rendered: boolean };
type SamplingCase = {
  why: string;
  object: Record<string, unknown>;
  shot: { duration: number; easing: string };
  samples: Record<string, number | Vec3>[];
};
const contract = JSON.parse(readFileSync(CONTRACT_PATH, "utf-8")) as {
  contract: string;
  version: number;
  tolerance: number;
  geometry: GeometryCase[];
  aids: AidCase[];
  sampling: { camera: SamplingCase; object: SamplingCase };
  lighting: {
    why: string;
    kelvin: { kelvin: number; rgb: Vec3 }[];
    sun: { azimuth: number; elevation: number; direction: Vec3 }[];
  };
};
/** 语料里的容差(米/度/归一化色值)换成 toBeCloseTo 的位数 —— 0.001 就是三位。 */
const DIGITS = Math.round(-Math.log10(contract.tolerance));

/** 语料只给「这个物体长什么样」,其余字段取工作台里新建物体的默认值。 */
function sceneObject(spec: Record<string, unknown>): SceneObject {
  return {
    id: "x",
    name: String(spec.kind ?? "x"),
    kind: spec.kind,
    position: [0, 0, 0],
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    color: "#cccccc",
    roughness: 0.8,
    metalness: 0,
    intensity: 1,
    hidden: false,
    ...spec,
    parameters: {
      width: 2, height: 2, depth: 2, radius: 1, steps: 8, door_width: 1.4, door_height: 2.3,
      ...((spec.parameters as Record<string, number>) ?? {}),
    },
  } as SceneObject;
}

function shotOf(spec: { duration: number; easing: string }): SceneShot {
  return { id: "s", name: "S", camera_id: "x", aspect: "16:9", ...spec } as SceneShot;
}

function closeTo(actual: ArrayLike<number>, expected: readonly number[], why: string) {
  expected.forEach((value, index) => expect(actual[index], why).toBeCloseTo(value, DIGITS));
}

describe("3D 场景契约(和后端跑同一份语料)", () => {
  it("语料在,而且有内容", () => {
    expect(contract.contract).toBe("scene-3d");
    expect(contract.geometry.length && contract.aids.length && contract.lighting.kelvin.length).toBeGreaterThan(0);
  });

  it.each(contract.geometry.map((one) => [one.name, one] as const))("几何 · %s", (_name, one) => {
    const node = geometryObject(sceneObject(one.object));
    const meshes: THREE.Mesh[] = [];
    node.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) meshes.push(child as THREE.Mesh);
    });
    expect(meshes.length, one.why).toBe(one.parts);
    const box = new THREE.Box3().setFromObject(node);
    closeTo(box.min.toArray(), one.min, one.why);
    closeTo(box.max.toArray(), one.max, one.why);
  });

  it.each(contract.aids.map((one) => [one.name, one] as const))("编辑辅助物 · %s", (_name, one) => {
    // 工作台**可以**画机位模型和灯泡标记(要能点中它们);契约管的是它们不算场景内容 ——
    // 后端渲染和导出里一块几何都不该有,那一侧由 test_scene_3d_parity.py 验。
    expect(one.rendered, one.why).toBe(false);
  });

  it("运镜的插值和后端一致", () => {
    const { object, shot, samples, why } = contract.sampling.camera;
    for (const sample of samples) {
      const pose = sampleCamera(sceneObject(object), shotOf(shot), sample.t as number);
      closeTo(pose.position, sample.position as Vec3, why);
      closeTo(pose.target, sample.target as Vec3, why);
      expect(pose.fov, why).toBeCloseTo(sample.fov as number, DIGITS);
    }
  });

  it("物体动画的插值和后端一致", () => {
    const { object, shot, samples, why } = contract.sampling.object;
    for (const sample of samples) {
      const pose = sampleObject(sceneObject(object), shotOf(shot), sample.t as number);
      closeTo(pose.position, sample.position as Vec3, why);
      closeTo(pose.rotation, sample.rotation as Vec3, why);
      closeTo(pose.scale, sample.scale as Vec3, why);
    }
  });

  it("光照换算和后端一致", () => {
    for (const one of contract.lighting.kelvin) closeTo(kelvinRgb(one.kelvin), one.rgb, contract.lighting.why);
    for (const one of contract.lighting.sun) {
      closeTo(sunDirection(one.azimuth, one.elevation), one.direction, contract.lighting.why);
    }
  });
});
