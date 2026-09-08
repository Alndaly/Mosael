import {
  cameraObserver,
  observationFrame,
  cameraInset,
  shotPathPoints,
} from "./sceneObservation";
import {
  attachSceneNavigation,
  type SceneNavigationMode,
} from "./sceneNavigation";
import { encodeShotVideo } from "./encodeVideo";
import { cloneSceneForExport } from "./sceneExport";
import React from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { gltfLoader } from "./gltfLoader";
import { kelvinRgb } from "./lighting";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";
import {
  readSceneModel,
  type SceneContent,
  type SceneObject,
  type SceneShot,
  type SceneLighting,
  type Vec3,
} from "@/api/domains/scenes";
import { cameraOfShot, sampleCamera, sampleObject } from "./sceneGraph";

/**
 * 某个 props 快照在某一刻的机位姿态。
 *
 * 视口拿到的是「当前镜头」,而运镜长在**那台相机物体**上 —— 所以每次都要先解析出机位。
 * 机位找不到时(理论上后端会拒这种场景)退到一个能看的默认视角,而不是抛 —— 视口是渲染层,
 * 让画面黑掉比给一个近似视角更糟。
 */
function frameAt(p: Props, time: number): CameraPose {
  const rig = cameraOfShot(p.content, p.shot);
  if (!rig) return { position: [8, 5, 8], target: [0, 1, 0], fov: 45 };
  return sampleCamera(rig, p.shot, time);
}

export type ViewportHandle = {
  camera: () => CameraPose;
  focus: () => void;
  placement: (halfWidth: number) => Vec3;
  view: (direction: "perspective" | "front" | "top") => void;
  editCamera: (shot: SceneShot, time: number) => void;
  frame: (shot: SceneShot, time: number, options?: { clay?: boolean }) => Promise<Blob>;
  glb: () => Promise<Blob>;
  record: (
    shot: SceneShot,
    signal: AbortSignal,
    progress: (n: number) => void,
  ) => Promise<Blob>;
};
type Props = {
  workspace: string;
  sceneId: string;
  content: SceneContent;
  selected: string | null;
  mode: "translate" | "rotate" | "scale";
  snap: boolean;
  navigation: SceneNavigationMode;
  shot: SceneShot;
  time: number;
  preview: boolean;
  observing?: boolean;
  onCameraView?: () => void;
  onSelect: (id: string | null) => void;
  /** 正在被手改姿态的那个物体 —— 它这一刻不跟着自己的轨走。见 SceneStudio 里 `posing`。 */
  posing?: string | null;
  onTransform: (id: string, patch: Partial<SceneObject>) => void;
  onError: (error: string) => void;
};
function disposeTree(root: THREE.Object3D) {
  root.traverse((o) => {
    if (o instanceof THREE.Mesh) {
      o.geometry.dispose();
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => m.dispose());
    }
  });
}
function geometryObject(o: SceneObject): THREE.Object3D {
  const group = new THREE.Group(),
    p = o.parameters;
  const material = new THREE.MeshStandardMaterial({
    color: o.color,
    roughness: o.roughness,
    metalness: o.metalness,
  });
  function box(w: number, h: number, d: number, x = 0, y = h / 2, z = 0) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    group.add(m);
  }
  if (o.kind === "box") box(p.width, p.height, p.depth);
  if (o.kind === "plane") box(p.width, 0.04, p.depth, 0, -0.02, 0);
  if (o.kind === "sphere" || o.kind === "cylinder") {
    const shape =
      o.kind === "sphere"
        ? new THREE.SphereGeometry(p.radius, 32, 20)
        : new THREE.CylinderGeometry(p.radius, p.radius, p.height, 32);
    const m = new THREE.Mesh(shape, material);
    m.position.y = o.kind === "sphere" ? p.radius : p.height / 2;
    m.castShadow = true;
    m.receiveShadow = true;
    group.add(m);
  }
  if (o.kind === "room") {
    const w = p.width,
      h = p.height,
      d = p.depth,
      door = Math.min(p.door_width, w * 0.85),
      dh = Math.min(p.door_height, h * 0.9),
      side = (w - door) / 2;
    box(w, 0.08, d, 0, -0.04, 0);
    box(0.15, h, d, -w / 2);
    box(0.15, h, d, w / 2);
    for (const z of [-d / 2, d / 2]) {
      box(side, h, 0.15, -(w + door) / 4, h / 2, z);
      box(side, h, 0.15, (w + door) / 4, h / 2, z);
      box(door, h - dh, 0.15, 0, dh + (h - dh) / 2, z);
    }
  }
  if (o.kind === "stairs")
    for (let i = 0; i < p.steps; i++)
      box(
        p.width,
        (p.height * (i + 1)) / p.steps,
        p.depth / p.steps,
        0,
        (p.height * (i + 1)) / p.steps / 2,
        -p.depth / 2 + (p.depth * (i + 0.5)) / p.steps,
      );
  /** 人物。**是给构图当尺子的,不是给人看脸的。**
   *
   * 用几个基本体拼一个概括的人形:关键是高度、肩宽、头的位置和站姿的重心 —— 相机在不在
   * 视平线上、门够不够高、桌子到不到手,靠这几样就判断得出来。做得再细也不会出现在成片里
   * (成片是模型生成的),反而会让人误以为它决定长相。
   *
   * 比例按 1.7 米的常见人体来分:头约 1/7.5 身高,肩宽约 1/4,腿约占下半身。 */
  if (o.kind === "figure") {
    const h = p.height;
    const shoulders = Math.max(p.width, 0.2);
    const thickness = Math.max(p.depth, 0.12);
    const headR = h * 0.066;
    const legH = h * 0.47;
    const torsoH = h * 0.33;
    const capsule = (radius: number, length: number, x: number, y: number, z = 0) => {
      const m = new THREE.Mesh(new THREE.CapsuleGeometry(radius, length, 4, 12), material);
      m.position.set(x, y, z);
      m.castShadow = true;
      m.receiveShadow = true;
      group.add(m);
    };
    // 双腿
    capsule(thickness * 0.42, legH - thickness * 0.84, -shoulders * 0.22, legH / 2);
    capsule(thickness * 0.42, legH - thickness * 0.84, shoulders * 0.22, legH / 2);
    // 躯干:用一个压扁的胶囊,肩比腰宽一点
    const torso = new THREE.Mesh(
      new THREE.CapsuleGeometry(thickness * 0.62, torsoH - thickness * 1.24, 4, 14),
      material,
    );
    torso.scale.set(shoulders / (thickness * 1.24), 1, 1);
    torso.position.y = legH + torsoH / 2;
    torso.castShadow = true;
    torso.receiveShadow = true;
    group.add(torso);
    // 双臂,自然垂在身侧
    const armH = h * 0.36;
    capsule(thickness * 0.3, armH - thickness * 0.6, -shoulders * 0.62, legH + torsoH - armH / 2);
    capsule(thickness * 0.3, armH - thickness * 0.6, shoulders * 0.62, legH + torsoH - armH / 2);
    // 头(含一小截脖子)
    capsule(headR * 0.4, headR * 0.6, 0, legH + torsoH + headR * 0.3);
    const head = new THREE.Mesh(new THREE.SphereGeometry(headR, 24, 16), material);
    head.position.y = h - headR;
    head.castShadow = true;
    head.receiveShadow = true;
    group.add(head);
  }
  /** 桌子:一块台面 + 四条腿。摆道具、定台面高度用 —— 这一页里它出现的频率仅次于地面。 */
  if (o.kind === "table") {
    const top = Math.min(0.06, p.height * 0.1);
    const leg = Math.min(0.08, Math.min(p.width, p.depth) * 0.09);
    box(p.width, top, p.depth, 0, p.height - top / 2);
    for (const sx of [-1, 1])
      for (const sz of [-1, 1])
        box(
          leg,
          p.height - top,
          leg,
          (sx * (p.width - leg)) / 2 * 0.92,
          (p.height - top) / 2,
          (sz * (p.depth - leg)) / 2 * 0.92,
        );
  }
  /** 机位。**它是场景里的物体,所以要看得见、选得中、拖得动。**
   *
   * 视锥按**这台相机真实的 fov** 画,不是一个固定形状 —— 它要能一眼看出"这台拍得宽还是窄"。
   * 机身摆在锥顶**后面**(+Z),因为相机看向 -Z:机身骑在锥顶上的话,近处的东西会被自己的
   * 机身挡住,而且看不出锥是从哪儿发出来的。
   *
   * 标上 editorOnly:它是**编辑期的道具**,不该出现在镜头画面和导出的参考帧里 ——
   * 相机不拍自己。 */
  if (o.kind === "camera") {
    group.userData.editorOnly = true;
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.3, 0.22, 0.42),
      new THREE.MeshStandardMaterial({ color: "#8fa2c8", roughness: 0.5, metalness: 0.1 }),
    );
    body.position.z = 0.24;
    group.add(body);
    const reach = 1.1;
    const half = Math.tan(THREE.MathUtils.degToRad(o.fov) / 2) * reach;
    const wide = half * (16 / 9); // 视锥按 16:9 画;比例是镜头的属性,不是相机的
    const corners: [number, number, number][] = [
      [-wide, -half, -reach],
      [wide, -half, -reach],
      [wide, half, -reach],
      [-wide, half, -reach],
    ];
    const points: THREE.Vector3[] = [];
    for (const c of corners)
      points.push(new THREE.Vector3(0, 0, 0), new THREE.Vector3(...c));
    for (let i = 0; i < corners.length; i++)
      points.push(
        new THREE.Vector3(...corners[i]),
        new THREE.Vector3(...corners[(i + 1) % 4]),
      );
    // 顶边中点画一个小三角,标出"哪边朝上" —— 只看一个方框分不出机位有没有翻转。
    points.push(new THREE.Vector3(-wide * 0.4, half, -reach), new THREE.Vector3(0, half * 1.5, -reach));
    points.push(new THREE.Vector3(wide * 0.4, half, -reach), new THREE.Vector3(0, half * 1.5, -reach));
    group.add(
      new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: "#9fbaff", transparent: true, opacity: 0.9 }),
      ),
    );
  }
  if (o.kind === "light") {
    const lamp = new THREE.PointLight(o.color, o.intensity, 50, 2);
    // 点光源的阴影要渲六个面,比平行光贵得多 —— 给一张小得多的图。它照的通常是局部,
    // 分辨率不够的代价远小于"加了盏灯却没有影子"。
    lamp.castShadow = true;
    lamp.shadow.mapSize.set(512, 512);
    lamp.shadow.bias = -0.005;
    group.add(lamp);
    const bulb = new THREE.Mesh(
      new THREE.SphereGeometry(0.12, 12, 8),
      new THREE.MeshBasicMaterial({ color: o.color }),
    );
    group.add(bulb);
  }
  if (!group.children.length) material.dispose();
  return group;
}
function applyTransform(target: THREE.Object3D, o: SceneObject) {
  target.position.fromArray(o.position);
  target.rotation.set(...(o.rotation.map(THREE.MathUtils.degToRad) as Vec3));
  target.scale.fromArray(o.scale);
  target.visible = !o.hidden;
  target.name = o.name;
  target.userData.sceneObjectId = o.id;
}
/** 某一刻的机位姿态。**不是关键帧** —— 关键帧可以只写一部分字段,这个是解算完的结果。 */
export type CameraPose = { position: Vec3; target: Vec3; fov: number };

/**
 * 让一个普通对象**按相机的约定**朝向目标(它的 -Z 指过去)。
 *
 * **不能直接用 `Object3D.lookAt`。** three 里那个方法对相机和对普通对象是两套约定:
 *
 *     if (this.isCamera || this.isLight) m.lookAt(position, target, up);   // -Z 指向目标
 *     else                               m.lookAt(target, position, up);   // +Z 指向目标
 *
 * 机位模型是个 Group,走的是后一条 —— 于是视锥(按 -Z 画的)正好背对目标,画面上就是一台
 * **方向相反的摄像机**。`Matrix4.lookAt` 没有这个分支,永远是相机那一套。
 */
export function aimLikeCamera(node: THREE.Object3D, target: Vec3) {
  node.quaternion.setFromRotationMatrix(
    new THREE.Matrix4().lookAt(node.position, new THREE.Vector3(...target), node.up),
  );
}

function pose(camera: THREE.PerspectiveCamera, frame: CameraPose) {
  camera.position.fromArray(frame.position);
  camera.up.set(0, 1, 0);
  camera.lookAt(new THREE.Vector3(...frame.target));
  camera.fov = frame.fov;
  camera.updateProjectionMatrix();
}
const aspectRatio = (shot: SceneShot) =>
  shot.aspect === "9:16" ? 9 / 16 : shot.aspect === "1:1" ? 1 : 16 / 9;
export const SceneViewport = React.forwardRef<ViewportHandle, Props>(
  function SceneViewport(props, ref) {
    const host = React.useRef<HTMLDivElement>(null),
      latest = React.useRef(props);
    latest.current = props;
    const runtime = React.useRef<{
      sync: () => void;
      selected: () => void;
      handle: ViewportHandle;
    } | null>(null);
    const [fatal, setFatal] = React.useState("");
    const [inset, setInset] = React.useState({
      width: 0,
      height: 0,
      right: 12,
      bottom: 12,
    });
    React.useImperativeHandle(
      ref,
      () => ({
        camera: () => runtime.current!.handle.camera(),
        focus: () => runtime.current?.handle.focus(),
        placement: (w) => runtime.current?.handle.placement(w) ?? [0, 0, 0],
        view: (v) => runtime.current?.handle.view(v),
        editCamera: (s, t) => runtime.current?.handle.editCamera(s, t),
        frame: (s, t, options) => runtime.current!.handle.frame(s, t, options),
        glb: () => runtime.current!.handle.glb(),
        record: (s, signal, p) => runtime.current!.handle.record(s, signal, p),
      }),
      [],
    );
    React.useEffect(() => {
      const element = host.current!;
      let renderer: THREE.WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch {
        setFatal("无法启动 3D 视窗，请检查图形加速设置。");
        return;
      }
      renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      // **影子此前从来没渲过。** 每个网格上都写着 castShadow/receiveShadow,但全局这一档
      // 从没打开 —— 那些标记是死的。而这一页产出的画面是要交给图像/视频模型当参考的:
      // 影子是模型判断"光从哪来"最强的线索,没有它,参考帧是一张平的图。
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      element.append(renderer.domElement);
      const scene = new THREE.Scene(),
        root = new THREE.Group();
      scene.add(root);
      const ambient = new THREE.HemisphereLight(0xffffff, 0x666879, 1.5);
      scene.add(ambient);
      const kelvinColor = (kelvin: number) => new THREE.Color(...kelvinRgb(kelvin));
      const sun = new THREE.DirectionalLight(0xffffff, 2.5);
      sun.position.set(4, 9, 5);
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      // 斜射到大平面上时的自阴影条纹(shadow acne)。normalBias 沿法线推一点,比单纯加大
      // bias 好 —— 后者会把接触阴影整体推离物体,脚下那圈"贴地感"就没了。
      sun.shadow.bias = -0.0004;
      sun.shadow.normalBias = 0.02;
      scene.add(sun, sun.target);
      /** 主光的方向单位向量。方位角 0 是 +Z(相机默认所在的一侧),顺时针转向 +X。 */
      const sunDirection = (azimuth: number, elevation: number) => {
        const a = THREE.MathUtils.degToRad(azimuth);
        const e = THREE.MathUtils.degToRad(elevation);
        return new THREE.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e));
      };
      let SUN_DIRECTION = sunDirection(35, 55);
      /** 点光源的阴影是六个面,一盏就抵得上好几盏平行光。场景允许 500 个物体,不封顶的话
       *  一屋子灯能把帧率拖到个位数,而**第五盏灯的影子对画面几乎没有贡献**。
       *  按场景里的先后取前几盏 —— 顺序是用户自己排的,比"随便挑几盏"讲得通。 */
      const SHADOW_CASTING_LIGHTS = 4;
      const capLightShadows = () => {
        let remaining = SHADOW_CASTING_LIGHTS;
        root.traverse((node) => {
          if (node instanceof THREE.PointLight) node.castShadow = remaining-- > 0;
        });
      };
      /** 平行光的阴影相机是个正交盒子,默认 ±5 —— 展厅那种二十来米的场景一出盒子就没影子。
       *  所以每次场景或打光变了都按包围球重新框一次:方向来自场景数据,这里只把光挪到罩得住
       *  的位置,再把盒子放到刚好包住。 */
      const fitShadow = () => {
        const light = latest.current.content.lighting;
        if (light) SUN_DIRECTION = sunDirection(light.azimuth, light.elevation);
        const bounds = new THREE.Box3().setFromObject(root);
        if (bounds.isEmpty()) return;
        const sphere = bounds.getBoundingSphere(new THREE.Sphere());
        const radius = Math.max(sphere.radius, 1);
        sun.position.copy(sphere.center).addScaledVector(SUN_DIRECTION, radius * 3);
        sun.target.position.copy(sphere.center);
        sun.target.updateMatrixWorld();
        const box = sun.shadow.camera;
        box.left = -radius * 1.25;
        box.right = radius * 1.25;
        box.top = radius * 1.25;
        box.bottom = -radius * 1.25;
        box.near = 0.1;
        box.far = radius * 6;
        box.updateProjectionMatrix();
      };
      /** 把主光调到当前场景数据说的样子。 */
      const applyLighting = (lighting: SceneLighting) => {
        sun.color.copy(kelvinColor(lighting.temperature));
        sun.intensity = lighting.intensity;
        // 软硬只有一个能调的旋钮:PCFSoft 的模糊半径。它不是物理意义上的面光源,但"硬光
        // 投影边缘锐利、柔光边缘化开"这一条读者看得出来,而那正是要传给模型的信息。
        sun.shadow.radius = 1 + lighting.softness * 12;
        sun.shadow.blurSamples = lighting.softness > 0.5 ? 16 : 8;
        fitShadow();
      };
      const grid = new THREE.GridHelper(40, 40, 0x6b7480, 0x6b7480);
      (grid.material as THREE.Material).transparent = true;
      (grid.material as THREE.Material).opacity = 0.17;
      grid.position.y = -0.09;
      scene.add(grid);
      const editorCamera = new THREE.PerspectiveCamera(45, 1, 0.05, 2000);
      editorCamera.position.set(12, 10, 14);
      const shootingCamera = new THREE.PerspectiveCamera(45, 1, 0.05, 2000);
      const observerCamera = new THREE.PerspectiveCamera(45, 1, 0.05, 2000);
      const observerOrbit = new OrbitControls(
        observerCamera,
        renderer.domElement,
      );
      observerOrbit.enableDamping = true;
      observerOrbit.enabled = false;
      const observer = cameraObserver();
      scene.add(observer.group);
      const orbit = new OrbitControls(editorCamera, renderer.domElement);
      orbit.target.set(0, 1, -3);
      orbit.enableDamping = true;
      const transform = new TransformControls(
        editorCamera,
        renderer.domElement,
      );
      const removeNavigation = attachSceneNavigation(
        renderer.domElement,
        () => (latest.current.observing ? observerOrbit : orbit),
        () => ({
          mode: latest.current.navigation,
          disabled: latest.current.preview || transform.dragging,
        }),
      );
      observerOrbit.minDistance = 0.1;
      observerOrbit.maxDistance = 1000;
      orbit.minDistance = 0.1;
      orbit.maxDistance = 1000;
      scene.add(transform.getHelper());
      const selection = new THREE.BoxHelper(new THREE.Object3D(), 0x8da9cf);
      scene.add(selection);
      selection.visible = false;
      let path: THREE.Line | null = null,
        alive = true,
        frameId = 0,
        generation = 0,
        lastSignature = "",
        modelsPending = 0;
      const failedModels = new Set<string>();
      const framedModels = new Set<string>();
      const objects = new Map<string, THREE.Object3D>(),
        models = new Map<string, Promise<THREE.Group>>(),
        modelRoots: THREE.Group[] = [],
        abort = new AbortController();
      const report = (e: unknown) => {
        if (alive)
          latest.current.onError(e instanceof Error ? e.message : String(e));
      };
      const loadModel = (id: string) => {
        if (!models.has(id)) {
          const promise = readSceneModel(
            props.workspace,
            props.sceneId,
            id,
            abort.signal,
          )
            .then((data) =>
              gltfLoader(renderer).parseAsync(
                new TextDecoder().decode(data.slice(0, 4)) === "glTF"
                  ? data
                  : new TextDecoder().decode(data),
                "",
              ),
            )
            .then((gltf) => {
              if (!alive) {
                disposeTree(gltf.scene);
                throw new Error("Model loading cancelled");
              }
              modelRoots.push(gltf.scene);
              return gltf.scene;
            });
          models.set(id, promise);
        }
        return models.get(id)!;
      };
      function select() {
        const p = latest.current,
          o = p.selected ? objects.get(p.selected) : null;
        if (o && !p.preview && !p.observing) transform.attach(o);
        else transform.detach();
        transform.setMode(p.mode);
        transform.setTranslationSnap(p.snap ? 0.25 : null);
        transform.setRotationSnap(p.snap ? Math.PI / 12 : null);
        transform.setScaleSnap(p.snap ? 0.1 : null);
        selection.visible = !!o && !p.preview && !p.observing;
        if (o) selection.setFromObject(o);
      }
      function sync() {
        const p = latest.current;
        // **背景不在这里常设。** 它是场景数据(导出成片时也用它),但编辑视角把它涂满整块
        // 画布,就成了一整片不透明的色块 —— 而这个应用其余每一页都是半透明、透着用户的
        // 自定义背景。按视图决定,见下面渲染那一段。
        ambient.intensity = p.content.ambient;
        if (p.content.lighting) applyLighting(p.content.lighting);
        const signature = JSON.stringify(p.content.objects);
        if (signature === lastSignature) {
          select();
          return;
        }
        lastSignature = signature;
        const gen = ++generation;
        transform.detach();
        disposeTree(root);
        root.clear();
        objects.clear();
        for (const o of p.content.objects) {
          const node = geometryObject(o);
          applyTransform(node, o);
          // 相机的朝向由 target 决定,不由欧拉角 —— 摆完变换再瞄一次。
          if (o.kind === "camera") aimLikeCamera(node, o.target);
          objects.set(o.id, node);
        }
        for (const o of p.content.objects) {
          const node = objects.get(o.id)!;
          (o.parent_id ? objects.get(o.parent_id)! : root).add(node);
          if (o.kind === "model" && o.model_id) {
            modelsPending++;
            loadModel(o.model_id)
              .then((model) => {
                if (!alive || generation !== gen) return;
                const copy = cloneSkeleton(model);
                copy.traverse((child) => {
                  delete child.userData.sceneObjectId;
                  if (child instanceof THREE.Mesh) {
                    // 导入的模型此前既不投影也不接影 —— 一整个 Blender 场景浮在光里,
                    // 而它恰恰是这一页最主要的内容。
                    child.castShadow = true;
                    child.receiveShadow = true;
                    child.geometry = child.geometry.clone();
                    child.material = Array.isArray(child.material)
                      ? child.material.map((m) => m.clone())
                      : child.material.clone();
                  }
                });
                node.add(copy);
                fitShadow();   // 模型有多大只有加载完才知道,阴影盒子要跟着重新框
                select();
                if (
                  !framedModels.has(o.id) &&
                  latest.current.selected === o.id &&
                  !latest.current.preview &&
                  !latest.current.observing
                )
                  handle.focus();
                framedModels.add(o.id);
              })
              .catch((error) => {
                if (o.model_id) failedModels.add(o.model_id);
                report(error);
              })
              .finally(() => {
                modelsPending--;
              });
          }
        }
        capLightShadows();
        fitShadow();
        select();
      }
      transform.addEventListener("dragging-changed", (event) => {
        orbit.enabled =
          !event.value && !latest.current.preview && !latest.current.observing;
        if (!event.value && transform.object) {
          const o = transform.object;
          latest.current.onTransform(o.userData.sceneObjectId, {
            position: o.position.toArray() as Vec3,
            rotation: [o.rotation.x, o.rotation.y, o.rotation.z].map(
              THREE.MathUtils.radToDeg,
            ) as Vec3,
            scale: o.scale
              .toArray()
              .map((v) => Math.max(0.001, Math.min(1000, v))) as Vec3,
          });
        }
      });
      transform.addEventListener("objectChange", () => {
        if (transform.object) selection.setFromObject(transform.object);
      });
      let down = { x: 0, y: 0 };
      const pointerDown = (e: PointerEvent) => {
        down = { x: e.clientX, y: e.clientY };
      };
      const pointerUp = (e: PointerEvent) => {
        if (
          latest.current.preview ||
          latest.current.observing ||
          transform.axis ||
          Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4 ||
          e.button !== 0
        )
          return;
        const rect = renderer.domElement.getBoundingClientRect(),
          ray = new THREE.Raycaster();
        ray.setFromCamera(
          new THREE.Vector2(
            ((e.clientX - rect.left) / rect.width) * 2 - 1,
            (-(e.clientY - rect.top) / rect.height) * 2 + 1,
          ),
          editorCamera,
        );
        const hit = ray.intersectObjects(root.children, true).find((h) => {
          let o: THREE.Object3D | null = h.object;
          while (o) {
            if (!o.visible) return false;
            o = o.parent;
          }
          return true;
        });
        let node = hit?.object;
        while (node && !node.userData.sceneObjectId)
          node = node.parent ?? undefined;
        latest.current.onSelect(node?.userData.sceneObjectId ?? null);
      };
      renderer.domElement.addEventListener("pointerdown", pointerDown);
      renderer.domElement.addEventListener("pointerup", pointerUp);
      const resize = new ResizeObserver(() => {
        const w = element.clientWidth,
          h = element.clientHeight;
        if (w && h) {
          renderer.setSize(w, h);
          observerCamera.aspect = w / h;
          observerCamera.updateProjectionMatrix();
          setInset(cameraInset(w, h, aspectRatio(latest.current.shot)));
          editorCamera.aspect = w / h;
          editorCamera.updateProjectionMatrix();
        }
      });
      resize.observe(element);
      let lastPath = "",
        observedShot = "";
      function frameOverview(
        direction: "perspective" | "front" | "top" = "perspective",
      ) {
        const bounds = new THREE.Box3().setFromObject(root);
        const framingRig = cameraOfShot(latest.current.content, latest.current.shot);
        for (const point of framingRig
          ? shotPathPoints(framingRig, latest.current.shot)
          : [])
          bounds.expandByPoint(point);
        const frame = observationFrame(
          bounds,
          observerCamera.aspect,
          direction,
        );
        observerOrbit.target.copy(frame.center);
        observerCamera.position.copy(frame.position);
        observerOrbit.update();
      }
      function render() {
        if (!alive) return;
        frameId = requestAnimationFrame(render);
        const p = latest.current;
        orbit.enabled = !p.preview && !p.observing && !transform.dragging;
        observerOrbit.enabled = !!p.observing;
        if (p.observing && observedShot !== p.shot.id) {
          frameOverview();
          observedShot = p.shot.id;
        }
        if (orbit.enabled) orbit.update();
        if (observerOrbit.enabled) observerOrbit.update();
        const rig = cameraOfShot(p.content, p.shot);
        const signature = JSON.stringify([
          rig?.track,
          rig?.position,
          rig?.target,
          rig?.fov,
          p.shot.duration,
          p.shot.easing,
        ]);
        if (signature !== lastPath) {
          lastPath = signature;
          if (path) {
            scene.remove(path);
            path.geometry.dispose();
            (path.material as THREE.Material).dispose();
          }
          path = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(rig ? shotPathPoints(rig, p.shot) : []),
            new THREE.LineBasicMaterial({
              color: 0xe9bc71,
              transparent: true,
              opacity: 0.9,
              depthTest: false,
            }),
          );
          path.renderOrder = 9;
          scene.add(path);
        }
        // **场景本身也会动。** 物体的轨和相机的轨在同一条时间轴上,所以每帧都要按当前时刻
        // 重摆一次 —— 但只在真的有东西在动的时候做,静态场景一帧也不该多算。
        //
        // 拖动操纵器时跳过:那时用户正在改的是**静止姿态**,每帧再按轨覆盖一次会把它拽回去。
        if (!transform.dragging)
          for (const o of p.content.objects) {
            if (!o.track.length) continue;
            // **正在手改的那个不采样。** 否则拖动操作杆是一件看不见的事:松手的下一帧就被
            // 采样值抹回去了。留住这个样子,直到用户按 `I` 把它记进这一刻(或换一个时刻)。
            if (o.id === p.posing) continue;
            const node = objects.get(o.id);
            if (!node) continue;
            if (o.kind === "camera") {
              // **机位模型也要跟着自己的轨走。** 此前这里把相机跳过了,于是它一直停在静止姿态,
              // 而「俯瞰全场」里那个取景器是按当前时刻算的 —— 同一台相机在画面上出现两个位置,
              // 看起来就是"机位错配"。会动的东西就该动,不分它是不是相机。
              const at = sampleCamera(o, p.shot, p.time);
              node.position.fromArray(at.position);
              aimLikeCamera(node, at.target);
              continue;
            }
            const at = sampleObject(o, p.shot, p.time);
            node.position.fromArray(at.position);
            node.rotation.set(...(at.rotation.map(THREE.MathUtils.degToRad) as Vec3));
            node.scale.fromArray(at.scale);
          }
        grid.visible = !p.preview;
        if (path) path.visible = !!p.observing;
        observer.group.visible = !!p.observing;
        transform.enabled = !p.preview && !p.observing;
        transform.getHelper().visible = transform.enabled && !!p.selected;
        selection.visible = !!p.selected && !p.preview && !p.observing;
        const w = element.clientWidth,
          h = element.clientHeight;
        if (!w || !h) return;
        const aspect = aspectRatio(p.shot),
          frame = frameAt(p, p.time);
        shootingCamera.aspect = aspect;
        pose(shootingCamera, frame);
        observer.update(frame);
        // 编辑期的道具(机位模型)不进镜头 —— 相机不拍自己。
        //
        // 这里**不再**为「俯瞰全场」额外藏掉当前那台:取景器已经不画视锥了(见
        // sceneObservation),它只补一条视线和目标点。一台相机在画面上只有一份表示。
        for (const node of root.children)
          if (node.userData.editorOnly) node.visible = !p.preview;
        // **编辑视角透明,镜头画面用场景底色。** 后者是**成片的一部分**(导出用的是同一个
        // 值),取景时必须看到真实底色;而编辑视角是工作台,它该跟应用其余页面一样透出背景。
        // 这也让 `p.preview` 分支里那句 setClearColor(…, 0) 真正生效 —— 此前 scene.background
        // 是不透明的,清成透明也会立刻被它盖掉。
        scene.background = p.preview ? new THREE.Color(p.content.background) : null;
        renderer.setScissorTest(false);
        renderer.setViewport(0, 0, w, h);
        if (p.preview) {
          const vw = Math.min(w, h * aspect),
            vh = vw / aspect;
          renderer.setClearColor(0x000000, 0);
          renderer.clear();
          renderer.setViewport((w - vw) / 2, (h - vh) / 2, vw, vh);
          renderer.setScissor((w - vw) / 2, (h - vh) / 2, vw, vh);
          renderer.setScissorTest(true);
          renderer.render(scene, shootingCamera);
        } else {
          renderer.setClearColor(0x000000, 0);
          renderer.clear();
          renderer.render(scene, p.observing ? observerCamera : editorCamera);
          if (p.observing) {
            const box = cameraInset(w, h, aspect);
            renderer.setViewport(
              w - box.width - box.right,
              box.bottom,
              box.width,
              box.height,
            );
            renderer.setScissor(
              w - box.width - box.right,
              box.bottom,
              box.width,
              box.height,
            );
            renderer.setScissorTest(true);
            renderer.clearDepth();
            grid.visible = false;
            if (path) path.visible = false;
            observer.group.visible = false;
            renderer.render(scene, shootingCamera);
            renderer.setScissorTest(false);
          }
        }
      }
      function output(shot: SceneShot, clay = false) {
        if (modelsPending) throw new Error("模型仍在加载，请稍后导出。");
        if (
          latest.current.content.objects.some(
            (o) => o.model_id && failedModels.has(o.model_id),
          )
        )
          throw new Error("有模型加载失败，请重新打开场景后再导出。");
        const r = new THREE.WebGLRenderer({
          antialias: true,
          preserveDrawingBuffer: true,
        });
        r.outputColorSpace = THREE.SRGBColorSpace;
        r.toneMapping = renderer.toneMapping;
        // **导出这一路也要开。** 视口里有影子而导出的参考帧没有,等于白做 —— 交给模型的
        // 就是这一帧。
        r.shadowMap.enabled = true;
        r.shadowMap.type = renderer.shadowMap.type;
        const aspect = aspectRatio(shot);
        r.setSize(
          aspect >= 1 ? 1280 : 720,
          Math.round((aspect >= 1 ? 1280 : 720) / aspect),
        );
        const exportScene = new THREE.Scene();
        // 灰模那一张换成中性底:场景自己的背景色会把整张图染上一层色偏,而这张图的用处
        // 恰恰是"只看光影"。
        exportScene.background = new THREE.Color(
          clay ? "#8a8f96" : latest.current.content.background,
        );
        const copy = cloneSceneForExport(root);
        if (clay) {
          /** 统一材质的"灰模"。**去掉材质噪音,只留光的结构。**
           *
           * 3D 里的占位球和默认色看着塑料,直接当参考图会把模型往塑料感带;而影子、明暗
           * 过渡、体积这些**光的信息**在灰模上反而更干净。它是配合正片一起送的第二张参考图,
           * 不是替代。
           *
           * clone(true) 不复制材质(是共享引用),所以在这里换掉不会动到视口里的那一份。 */
          const clayMaterial = new THREE.MeshStandardMaterial({
            color: 0xbfc3c8,
            roughness: 0.85,
            metalness: 0,
          });
          copy.traverse((node) => {
            if (node instanceof THREE.Mesh) node.material = clayMaterial;
          });
        }
        const exportSun = sun.clone();
        // 平行光的朝向由 target 决定,而 clone 出来的 target 不在任何场景里 —— 不加进去,
        // 它的世界矩阵就不参与更新,光会照着默认方向(原点)打。
        exportScene.add(copy, ambient.clone(), exportSun, exportSun.target);
        const camera = new THREE.PerspectiveCamera(45, aspect, 0.05, 2000);
        // **导出的画面里物体也要动。** 克隆出来的是静止姿态,每一帧都要按轨重摆 ——
        // 否则参考视频里相机在走、人却站着不动,而"人在走"恰恰是交给视频模型最有价值的条件。
        const moving = latest.current.content.objects.filter(
          (o) => o.kind !== "camera" && o.track.length,
        );
        const byId = new Map<string, THREE.Object3D>();
        copy.traverse((node) => {
          const id = node.userData.sceneObjectId;
          if (typeof id === "string" && !byId.has(id)) byId.set(id, node);
        });
        return {
          r,
          draw: (time: number) => {
            for (const object of moving) {
              const node = byId.get(object.id);
              if (!node) continue;
              const at = sampleObject(object, shot, time);
              node.position.fromArray(at.position);
              node.rotation.set(...(at.rotation.map(THREE.MathUtils.degToRad) as Vec3));
              node.scale.fromArray(at.scale);
            }
            pose(camera, frameAt({ ...latest.current, shot }, time));
            r.render(exportScene, camera);
          },
        };
      }
      const handle: ViewportHandle = {
        camera: () => ({
          time: 0,
          position: editorCamera.position.toArray() as Vec3,
          target: orbit.target.toArray() as Vec3,
          fov: editorCamera.fov,
        }),
        placement: (halfWidth) => {
          const bounds = new THREE.Box3().setFromObject(root);
          return bounds.isEmpty()
            ? [0, 0, 0]
            : [
                bounds.max.x + halfWidth + 0.75,
                0,
                bounds.getCenter(new THREE.Vector3()).z,
              ];
        },
        focus: () => {
          if (latest.current.observing) {
            frameOverview();
            return;
          }
          const target = latest.current.selected
            ? objects.get(latest.current.selected)
            : root;
          if (!target) return;
          const b = new THREE.Box3().setFromObject(target);
          if (b.isEmpty()) return;
          const c = b.getCenter(new THREE.Vector3());
          const radius = Math.max(
            1,
            b.getBoundingSphere(new THREE.Sphere()).radius,
          );
          const vertical = THREE.MathUtils.degToRad(editorCamera.fov);
          const horizontal =
            2 * Math.atan(Math.tan(vertical / 2) * editorCamera.aspect);
          const distance =
            (radius / Math.sin(Math.min(vertical, horizontal) / 2)) * 1.12;
          const direction = editorCamera.position
            .clone()
            .sub(orbit.target)
            .normalize();
          orbit.target.copy(c);
          editorCamera.position.copy(c).addScaledVector(direction, distance);
          editorCamera.far = Math.max(2000, distance * 10);
          editorCamera.updateProjectionMatrix();
        },
        view: (direction) => {
          if (latest.current.observing) {
            frameOverview(direction);
            return;
          }
          const target = orbit.target.clone();
          const distance = Math.max(
            5,
            editorCamera.position.distanceTo(target),
          );
          const axis =
            direction === "top"
              ? new THREE.Vector3(0, 1, 0.001)
              : direction === "front"
                ? new THREE.Vector3(0, 0, 1)
                : new THREE.Vector3(1, 0.7, 1).normalize();
          orbit.update();
          editorCamera.position.copy(target).addScaledVector(axis, distance);
          orbit.update();
          handle.focus();
        },
        editCamera: (shot, time) => {
          const frame = frameAt({ ...latest.current, shot }, time);
          orbit.update();
          pose(editorCamera, frame);
          orbit.target.fromArray(frame.target);
          orbit.update();
        },
        frame: async (shot, time, options) => {
          const { r, draw } = output(shot, options?.clay);
          try {
            draw(time);
            return await new Promise<Blob>((resolve, reject) =>
              r.domElement.toBlob(
                (b) => (b ? resolve(b) : reject(new Error("无法导出图片"))),
                "image/png",
              ),
            );
          } finally {
            r.dispose();
          }
        },
        glb: async () => {
          if (modelsPending) throw new Error("模型仍在加载");
          if (
            latest.current.content.objects.some(
              (o) => o.model_id && failedModels.has(o.model_id),
            )
          )
            throw new Error("有模型加载失败，请重新打开场景后再导出。");
          const data = await new GLTFExporter().parseAsync(cloneSceneForExport(root), {
            binary: true,
          });
          if (!(data instanceof ArrayBuffer)) throw new Error("无法导出 GLB");
          return new Blob([data], { type: "model/gltf-binary" });
        },
        record: async (shot, signal, progress) => {
          const outputFrame = output(shot);
          try {
            const encoded = await encodeShotVideo(
              outputFrame.r.domElement,
              shot.duration,
              outputFrame.draw,
              signal,
              progress,
            );
            if (encoded) return encoded;
          } finally {
            outputFrame.r.dispose();
          }
          const type = [
            "video/webm;codecs=vp9",
            "video/webm;codecs=vp8",
            "video/webm",
          ].find(
            (t) =>
              typeof MediaRecorder !== "undefined" &&
              MediaRecorder.isTypeSupported(t),
          );
          if (!type) throw new Error("当前浏览器不支持视频预览导出");
          const { r, draw } = output(shot);
          draw(0);
          const stream = r.domElement.captureStream(30);
          const recorder = new MediaRecorder(stream, {
            mimeType: type,
            videoBitsPerSecond: 6000000,
          });
          const chunks: Blob[] = [];
          try {
            return await new Promise<Blob>((resolve, reject) => {
              let raf = 0,
                failed = false;
              const cancel = () => {
                failed = true;
                cancelAnimationFrame(raf);
                if (recorder.state !== "inactive") recorder.stop();
                reject(new Error("已取消导出"));
              };
              signal.addEventListener("abort", cancel, { once: true });
              recorder.ondataavailable = (e) => {
                if (e.data.size) chunks.push(e.data);
              };
              recorder.onerror = () => {
                failed = true;
                cancelAnimationFrame(raf);
                signal.removeEventListener("abort", cancel);
                if (recorder.state !== "inactive") recorder.stop();
                reject(new Error("视频录制失败"));
              };
              recorder.onstop = () => {
                cancelAnimationFrame(raf);
                signal.removeEventListener("abort", cancel);
                if (!failed) resolve(new Blob(chunks, { type: "video/webm" }));
              };
              recorder.start(100);
              const start = performance.now();
              function tick() {
                if (signal.aborted || !alive) {
                  cancel();
                  return;
                }
                const t = Math.min(
                  shot.duration,
                  (performance.now() - start) / 1000,
                );
                draw(t);
                progress(t / shot.duration);
                if (t >= shot.duration) {
                  recorder.stop();
                  return;
                }
                raf = requestAnimationFrame(tick);
              }
              tick();
            });
          } finally {
            stream.getTracks().forEach((t) => t.stop());
            r.dispose();
          }
        },
      };
      runtime.current = { sync, selected: select, handle };
      sync();
      render();
      return () => {
        alive = false;
        abort.abort();
        cancelAnimationFrame(frameId);
        resize.disconnect();
        transform.dispose();
        removeNavigation();
        observerOrbit.dispose();
        observer.dispose();
        orbit.dispose();
        selection.geometry.dispose();
        (selection.material as THREE.Material).dispose();
        disposeTree(root);
        for (const model of modelRoots) {
          model.traverse((o) => {
            if (o instanceof THREE.Mesh) {
              const mats = Array.isArray(o.material)
                ? o.material
                : [o.material];
              mats.forEach((m) =>
                Object.values(m).forEach((v) => {
                  if (v instanceof THREE.Texture) v.dispose();
                }),
              );
            }
          });
          disposeTree(model);
        }
        if (path) {
          path.geometry.dispose();
          (path.material as THREE.Material).dispose();
        }
        grid.geometry.dispose();
        (grid.material as THREE.Material).dispose();
        renderer.dispose();
        renderer.domElement.remove();
        runtime.current = null;
      };
    }, [props.workspace, props.sceneId]);
    React.useEffect(() => {
      runtime.current?.sync();
    }, [props.content]);
    React.useEffect(() => {
      runtime.current?.selected();
    }, [
      props.selected,
      props.mode,
      props.snap,
      props.preview,
      props.observing,
    ]);
    React.useEffect(() => {
      const el = host.current;
      if (el)
        setInset(
          cameraInset(el.clientWidth, el.clientHeight, aspectRatio(props.shot)),
        );
    }, [props.shot.aspect]);
    return (
      <div className="scene-viewport" ref={host} aria-label="3D 场景视窗">
        {props.observing && !fatal && (
          <>
            <div className="scene-motion-legend">
              <span />
              摄像机动线<small>蓝色为当前摄像机，虚线指向取景中心</small>
            </div>
            <button
              className="scene-camera-inset"
              style={inset}
              aria-label="放大镜头画面"
              onClick={props.onCameraView}
            >
              <span>
                镜头画面 <small>{props.time.toFixed(1)} s ↗</small>
              </span>
            </button>
          </>
        )}
        {fatal && (
          <div className="scene-empty" role="alert">
            {fatal}
          </div>
        )}
      </div>
    );
  },
);
