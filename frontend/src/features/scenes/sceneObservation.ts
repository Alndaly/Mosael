import * as THREE from "three";
import type { CameraFrame, SceneShot } from "@/api/domains/scenes";
import { sampleCamera } from "./sceneGraph";

export function shotPathPoints(shot: SceneShot) {
  return Array.from(
    { length: 101 },
    (_, i) =>
      new THREE.Vector3(
        ...sampleCamera(shot, (shot.duration * i) / 100).position,
      ),
  );
}

/** Keep the inset inside short/narrow viewports, using the same CSS-pixel rectangle as WebGL. */
export function cameraInset(width: number, height: number, aspect: number) {
  const w = Math.max(1, Math.min(288, width * 0.36, (height - 64) * aspect));
  const h = w / aspect;
  return { width: w, height: h, right: 12, bottom: 12 };
}

/** Observation aids live outside the scene root, so they can never appear in exported frames. */
export function cameraObserver() {
  const group = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(45, 16 / 9, 0.2, 1.5);
  const frustum = new THREE.CameraHelper(camera);
  const blue = new THREE.Color(0x9fbaff);
  frustum.setColors(blue, blue, new THREE.Color(0xffffff), blue, blue);
  for (const material of Array.isArray(frustum.material)
    ? frustum.material
    : [frustum.material]) {
    material.depthTest = false;
    material.transparent = true;
    material.opacity = 0.8;
  }
  frustum.renderOrder = 10;
  const marker = new THREE.Mesh(
    new THREE.BoxGeometry(0.28, 0.2, 0.35),
    new THREE.MeshBasicMaterial({ color: 0x9fbaff, depthTest: false }),
  );
  marker.name = "camera-position";
  marker.renderOrder = 11;
  const target = new THREE.Mesh(
    new THREE.SphereGeometry(0.09, 12, 8),
    new THREE.MeshBasicMaterial({ color: 0xe9bc71, depthTest: false }),
  );
  target.name = "camera-target";
  target.renderOrder = 11;
  const sight = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(),
    ]),
    new THREE.LineDashedMaterial({
      color: 0x9fbaff,
      dashSize: 0.18,
      gapSize: 0.12,
      transparent: true,
      opacity: 0.65,
      depthTest: false,
    }),
  );
  group.add(frustum, marker, target, sight);
  return {
    group,
    update(frame: CameraFrame, aspect: number) {
      camera.position.fromArray(frame.position);
      camera.lookAt(new THREE.Vector3(...frame.target));
      camera.fov = frame.fov;
      camera.aspect = aspect;
      camera.updateProjectionMatrix();
      camera.updateMatrixWorld(true);
      frustum.update();
      marker.position.copy(camera.position);
      marker.quaternion.copy(camera.quaternion);
      target.position.fromArray(frame.target);
      const points = sight.geometry.attributes.position;
      points.setXYZ(0, ...frame.position);
      points.setXYZ(1, ...frame.target);
      points.needsUpdate = true;
      sight.geometry.computeBoundingSphere();
      sight.computeLineDistances();
    },
    dispose() {
      frustum.dispose();
      marker.geometry.dispose();
      marker.material.dispose();
      target.geometry.dispose();
      target.material.dispose();
      sight.geometry.dispose();
      sight.material.dispose();
    },
  };
}

/** Fit the scene and its route to the chosen observation direction, without a loose bounding sphere. */
export function observationFrame(
  bounds: THREE.Box3,
  aspect: number,
  direction: "perspective" | "front" | "top" = "perspective",
) {
  const center = bounds.getCenter(new THREE.Vector3());
  const axis =
    direction === "top"
      ? new THREE.Vector3(0, 1, 0.001).normalize()
      : direction === "front"
        ? new THREE.Vector3(0, 0, 1)
        : new THREE.Vector3(1, 0.85, 1).normalize();
  const right = new THREE.Vector3(0, 1, 0).cross(axis).normalize();
  const up = axis.clone().cross(right);
  const tangent = Math.tan(THREE.MathUtils.degToRad(45) / 2);
  let distance = 4;
  for (const x of [bounds.min.x, bounds.max.x])
    for (const y of [bounds.min.y, bounds.max.y])
      for (const z of [bounds.min.z, bounds.max.z]) {
        const offset = new THREE.Vector3(x, y, z).sub(center);
        distance = Math.max(
          distance,
          offset.dot(axis) +
            1.15 *
              Math.max(
                Math.abs(offset.dot(right)) / (tangent * aspect),
                Math.abs(offset.dot(up)) / tangent,
              ),
        );
      }
  return { center, position: center.clone().addScaledVector(axis, distance) };
}
