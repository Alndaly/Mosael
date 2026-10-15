import * as THREE from "three";

/**
 * 人偶着色快照:把当前姿势的人偶渲成一张**干净的 PNG** 喂给生图。
 *
 * 渲染路径**独立于场景视口**(sceneExport 那一条是给场景镜头的:按机位、按轨、按场景底色,
 * 而人偶快照有自己的要求)——离屏 `WebGLRenderer` + 中性纯色底 + 摄影棚三灯 + 相机按人偶
 * 包围球**紧框**(框得紧,空白自然裁掉,不用后处理裁图)。
 *
 * 产出走 `importAsset` 进素材库(见 SceneMannequinDialog),之后生图节点的「要模型看的图片」
 * (`image_asset_ids`)就能引用它 —— 这条链**不动后端**。
 */

export type MannequinSnapshotSize = "square" | "portrait";

export const MANNEQUIN_SNAPSHOT_SIZES: Record<MannequinSnapshotSize, { width: number; height: number }> = {
  square: { width: 1024, height: 1024 },
  portrait: { width: 768, height: 1024 },
};

/** 中性暖灰底:不抢人偶的暖木色,也足够亮,模型读得清轮廓和投影。 */
export const MANNEQUIN_SNAPSHOT_BACKGROUND = 0xefede6;

/** 观察方向:正面偏右、略高 —— 能同时读到脸侧、胸厚和脚的站位。 */
const VIEW_DIRECTION = new THREE.Vector3(0.45, 0.18, 1);

export type CameraFrame = {
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
};

/**
 * 按包围球把相机放到「刚好罩住」的位置。**横竖通用**:限制方向取竖直/水平半角里更紧的那个,
 * 竖图(`aspect < 1`)时宽度先顶到边,人不会出头。
 *
 * 纯函数(three 的矩阵数学,不需要 WebGL)——取景对不对由 node 测试钉。
 */
export function frameMannequinCamera(
  box: THREE.Box3,
  aspect: number,
  fov = 38,
  direction: THREE.Vector3 = VIEW_DIRECTION,
): CameraFrame {
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const radius = Math.max(sphere.radius, 0.001);
  const verticalHalf = THREE.MathUtils.degToRad(fov) / 2;
  const horizontalHalf = Math.atan(Math.tan(verticalHalf) * aspect);
  // 1.08 的边距:贴太近肢体顶到边,留白一圈才对得起"快照"。
  const distance = (radius / Math.sin(Math.min(verticalHalf, horizontalHalf))) * 1.08;
  const position = sphere.center
    .clone()
    .addScaledVector(direction.clone().normalize(), distance);
  return {
    position: position.toArray() as [number, number, number],
    target: sphere.center.toArray() as [number, number, number],
    fov,
  };
}

/** 摄影棚三灯:天光打底、主光投影、对面补光把暗面托起来(含主光的 target)。 */
function studioLighting(target: THREE.Object3D): THREE.Object3D[] {
  const ambient = new THREE.HemisphereLight(0xffffff, 0x9a9284, 1.15);
  const key = new THREE.DirectionalLight(0xfff6ea, 2.4);
  key.position.set(2.6, 3.6, 2.4);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.02;
  const box = new THREE.Box3().setFromObject(target);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const radius = Math.max(sphere.radius, 0.5);
  key.shadow.camera.left = -radius * 1.3;
  key.shadow.camera.right = radius * 1.3;
  key.shadow.camera.top = radius * 1.3;
  key.shadow.camera.bottom = -radius * 1.3;
  key.shadow.camera.near = 0.1;
  key.shadow.camera.far = radius * 8;
  key.target.position.copy(sphere.center);
  const fill = new THREE.DirectionalLight(0xdfe8ff, 0.9);
  fill.position.set(-3, 1.6, 1.8);
  return [ambient, key, key.target, fill];
}

/**
 * 把 `source`(人偶根)渲成 PNG Blob。
 *
 * **内部自己克隆** —— 克隆共享几何和材质,便宜;而离屏场景会接管根节点的父级,
 * 直接拿挂在视口里的那棵会把编辑画面掏空。调用处放心传 `rig.root`。
 */
export async function renderMannequinSnapshot(
  source: THREE.Object3D,
  size: MannequinSnapshotSize = "square",
): Promise<Blob> {
  const { width, height } = MANNEQUIN_SNAPSHOT_SIZES[size];
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  try {
    renderer.setPixelRatio(1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.setSize(width, height);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(MANNEQUIN_SNAPSHOT_BACKGROUND);
    const subject = source.clone(true);
    scene.add(subject);
    for (const light of studioLighting(subject)) scene.add(light);

    const aspect = width / height;
    const camera = new THREE.PerspectiveCamera(38, aspect, 0.05, 100);
    const frame = frameMannequinCamera(
      new THREE.Box3().setFromObject(subject),
      aspect,
      camera.fov,
    );
    camera.position.fromArray(frame.position);
    camera.lookAt(new THREE.Vector3(...frame.target));
    camera.updateProjectionMatrix();

    renderer.render(scene, camera);
    return await new Promise<Blob>((resolve, reject) =>
      renderer.domElement.toBlob(
        (blob) =>
          blob
            ? resolve(blob)
            : reject(new Error("mannequin snapshot produced an empty image")),
        "image/png",
      ),
    );
  } finally {
    renderer.dispose();
  }
}
