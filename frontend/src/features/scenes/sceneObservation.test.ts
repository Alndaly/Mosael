import { expect, it } from "vitest";
import * as THREE from "three";
import { makeShot, sampleCamera } from "./sceneGraph";
import { aimLikeCamera } from "./SceneViewport";
import {
  cameraInset,
  cameraObserver,
  observationFrame,
  shotPathPoints,
} from "./sceneObservation";

it("瞄准提示画的是「看着哪个点」,而不是再画一台相机", () => {
  // 取景器此前还画一份视锥和机身 —— 和机位模型完全重复。**而且朝向相反**:机位模型是个
  // 普通 Object3D,`lookAt` 对它是 +Z 朝向目标,而视锥按 -Z 画 —— 正好差 180°,画面上就是
  // 两台方向相反的摄像机。视锥归机位模型画,这里只留机位模型给不出的那件事:它看着哪儿。
  const { camera, shot } = makeShot();
  camera.track = [
    { time: 0, position: [0, 2, 8], target: [0, 1, 0], fov: 40 },
    { time: 5, position: [8, 4, 0], target: [1, 1, 0], fov: 70 },
  ];
  const observer = cameraObserver();
  try {
    expect(observer.group.getObjectByName("camera-position"), "机身不该再画一份").toBeUndefined();
    for (const easing of ["linear", "smooth"] as const) {
      shot.easing = easing;
      const points = shotPathPoints(camera, shot);
      for (const i of [0, 25, 50, 100]) {
        const frame = sampleCamera(camera, shot, (shot.duration * i) / 100);
        observer.update(frame);
        expect(points[i].toArray()).toEqual(frame.position);
        expect(
          observer.group.getObjectByName("camera-target")!.position.toArray(),
        ).toEqual(frame.target);
        // 视线两端就是"从哪儿看"和"看哪儿",不能有一端落在别处。
        const sight = observer.group.children.find((c) => c instanceof THREE.Line) as THREE.Line;
        const ends = sight.geometry.attributes.position;
        expect([ends.getX(0), ends.getY(0), ends.getZ(0)]).toEqual(frame.position);
        expect([ends.getX(1), ends.getY(1), ends.getZ(1)]).toEqual(frame.target);
      }
    }
  } finally {
    observer.dispose();
  }
});

it("机位模型按相机约定朝向目标 —— 不是反的", () => {
  // 这条钉的是那个 180° 的根因。three 的 Object3D.lookAt 有两套约定:
  //   相机/灯:  m.lookAt(position, target, up)  → -Z 指向目标
  //   其它对象:  m.lookAt(target, position, up)  → +Z 指向目标
  // 机位模型是 Group,走后一条;而视锥按 -Z 画。两者相差正好 180°。
  const eye: [number, number, number] = [0, 2, 6];
  const at: [number, number, number] = [0, 1, -3];

  const naive = new THREE.Group();
  naive.position.fromArray(eye);
  naive.lookAt(new THREE.Vector3(...at));

  const fixed = new THREE.Group();
  fixed.position.fromArray(eye);
  aimLikeCamera(fixed, at);

  const forwardOf = (node: THREE.Object3D) =>
    new THREE.Vector3(0, 0, -1).applyQuaternion(node.quaternion);
  const wanted = new THREE.Vector3(...at).sub(new THREE.Vector3(...eye)).normalize();

  expect(forwardOf(fixed).distanceTo(wanted)).toBeLessThan(1e-8);
  // 直接用 lookAt 的那个正好背过去 —— 留着这条断言,是为了让"为什么不能直接用"有据可查。
  expect(forwardOf(naive).distanceTo(wanted)).toBeGreaterThan(1.9);
});

it.each([
  [1200, 600, 16 / 9],
  [600, 240, 9 / 16],
  [320, 180, 1],
])(
  "fits a synchronized inset inside %i × %i without distorting its aspect ratio",
  (w, h, aspect) => {
    const box = cameraInset(w, h, aspect);
    expect(box.width / box.height).toBeCloseTo(aspect);
    expect(box.width + box.right).toBeLessThan(w);
    expect(box.height + box.bottom + 25).toBeLessThan(h);
    expect(box.width).toBeLessThanOrEqual(288);
  },
);

it("fits the full scene and route in portrait and landscape observation cameras", () => {
  const bounds = new THREE.Box3(
    new THREE.Vector3(-3, 0, -20),
    new THREE.Vector3(10, 6, 10),
  );
  for (const aspect of [16 / 9, 9 / 16])
    for (const direction of ["perspective", "front", "top"] as const) {
      const frame = observationFrame(bounds, aspect, direction);
      const camera = new THREE.PerspectiveCamera(45, aspect, 0.05, 2000);
      camera.position.copy(frame.position);
      camera.lookAt(frame.center);
      camera.updateMatrixWorld(true);
      for (const x of [bounds.min.x, bounds.max.x])
        for (const y of [bounds.min.y, bounds.max.y])
          for (const z of [bounds.min.z, bounds.max.z]) {
            const point = new THREE.Vector3(x, y, z).project(camera);
            expect(Math.abs(point.x)).toBeLessThan(1);
            expect(Math.abs(point.y)).toBeLessThan(1);
            expect(Math.abs(point.z)).toBeLessThan(1);
          }
    }
});
