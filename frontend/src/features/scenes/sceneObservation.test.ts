import { expect, it } from "vitest";
import * as THREE from "three";
import { makeShot, sampleCamera } from "./sceneGraph";
import {
  cameraInset,
  cameraObserver,
  observationFrame,
  shotPathPoints,
} from "./sceneObservation";

it("keeps the route and animated camera on the same sampled shot, including easing and FOV", () => {
  const shot = makeShot();
  shot.frames = [
    { time: 0, position: [0, 2, 8], target: [0, 1, 0], fov: 40 },
    { time: 5, position: [8, 4, 0], target: [1, 1, 0], fov: 70 },
  ];
  const observer = cameraObserver();
  try {
    for (const easing of ["linear", "smooth"] as const) {
      shot.easing = easing;
      const points = shotPathPoints(shot);
      for (const i of [0, 25, 50, 100]) {
        const frame = sampleCamera(shot, (shot.duration * i) / 100);
        observer.update(frame, 9 / 16);
        expect(points[i].toArray()).toEqual(frame.position);
        const marker = observer.group.getObjectByName("camera-position")!;
        expect(marker.position.toArray()).toEqual(frame.position);
        expect(
          observer.group.getObjectByName("camera-target")!.position.toArray(),
        ).toEqual(frame.target);
        const direction = new THREE.Vector3(0, 0, -1).applyQuaternion(
          marker.quaternion,
        );
        const expected = new THREE.Vector3(...frame.target)
          .sub(marker.position)
          .normalize();
        expect(direction.distanceTo(expected)).toBeLessThan(1e-8);
        const helper = observer.group.children[0] as THREE.CameraHelper;
        expect((helper.camera as THREE.PerspectiveCamera).fov).toBe(frame.fov);
        expect((helper.camera as THREE.PerspectiveCamera).aspect).toBe(9 / 16);
      }
    }
  } finally {
    observer.dispose();
  }
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
