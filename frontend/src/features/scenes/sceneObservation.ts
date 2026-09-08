import * as THREE from "three";
import type { SceneObject, SceneShot, Vec3 } from "@/api/domains/scenes";
import { sampleCamera } from "./sceneGraph";

/** 一台机位在整个镜头里走过的路径。**静止的机位没有路径** —— 它只是一个点。 */
export function shotPathPoints(camera: SceneObject, shot: SceneShot) {
  return Array.from(
    { length: 101 },
    (_, i) =>
      new THREE.Vector3(
        ...sampleCamera(camera, shot, (shot.duration * i) / 100).position,
      ),
  );
}

/** Keep the inset inside short/narrow viewports, using the same CSS-pixel rectangle as WebGL. */
export function cameraInset(width: number, height: number, aspect: number) {
  const w = Math.max(1, Math.min(288, width * 0.36, (height - 64) * aspect));
  const h = w / aspect;
  return { width: w, height: h, right: 12, bottom: 12 };
}

/**
 * 「俯瞰全场」里的**瞄准提示**:目标点 + 一条从机位射向它的虚线。
 *
 * **它不再画视锥和机身。** 相机现在是场景里的物体,自己就有机位模型(带按 fov 画的视锥)——
 * 这里再画一遍就是同一台相机的两份表示,重叠、抢深度,而且此前两者朝向还相反
 * (见 SceneViewport 的 aimLikeCamera:Object3D.lookAt 对普通对象是 +Z 朝向目标)。
 *
 * 留下来的这两样是机位模型没有的:**它在看哪个点**。运镜设计时那是最要紧的信息 ——
 * 位置和朝向能从模型上读出来,而"看着哪儿"读不出来。
 *
 * 这些辅助放在场景根之外,所以永远不会出现在导出的画面里。
 */
export function cameraObserver() {
  const group = new THREE.Group();
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
  group.add(target, sight);
  return {
    group,
    /** `aspect` 不再需要(视锥归机位模型画),但调用点还传着 —— 留着签名不动,少一处要改的地方。 */
    update(frame: { position: Vec3; target: Vec3 }) {
      target.position.fromArray(frame.target);
      const points = sight.geometry.attributes.position;
      points.setXYZ(0, ...frame.position);
      points.setXYZ(1, ...frame.target);
      points.needsUpdate = true;
      sight.geometry.computeBoundingSphere();
      sight.computeLineDistances();
    },
    dispose() {
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
