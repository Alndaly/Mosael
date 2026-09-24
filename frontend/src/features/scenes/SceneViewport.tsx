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
import { cloneSceneForExport, visibleBounds } from "./sceneExport";
import React from "react";
import * as THREE from "three";

import { SceneAxisGizmo } from "./SceneAxisGizmo";
import { axisVector, type AxisName, type Orientation } from "./axisGizmo";
import { createInfiniteGrid } from "./infiniteGrid";
import { geometryObject } from "./sceneMeshes";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { gltfLoader } from "./gltfLoader";
import { kelvinRgb, sunDirection } from "./lighting";
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
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";

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
function applyTransform(target: THREE.Object3D, o: SceneObject) {
  target.position.fromArray(o.position);
  target.rotation.set(...(o.rotation.map(THREE.MathUtils.degToRad) as Vec3));
  target.scale.fromArray(o.scale);
  target.visible = !o.hidden;
  target.name = o.name;
  target.userData.sceneObjectId = o.id;
  // 可见性记一份在数据上:相机道具的 `visible` 每帧按视图重设(见渲染循环),读它分不出
  // "藏了"和"这一刻不画",而选中框、操纵器要的是前者。
  target.userData.hidden = o.hidden;
}
/** 它自己和所有上级都没藏。**藏一个组 = 组里的东西都看不见**,孩子们自己的标记不动。 */
function shownInTree(node: THREE.Object3D, root: THREE.Object3D) {
  for (let n: THREE.Object3D | null = node; n && n !== root; n = n.parent)
    if (n.userData.hidden) return false;
  return true;
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
    const t = useI18n();
    /** 渲染循环那个 effect 只跑一次,里面抛的错要用**当前**语言 —— 所以走 ref。 */
    const translate = React.useRef(t);
    translate.current = t;
    const runtime = React.useRef<{
      sync: () => void;
      selected: () => void;
      handle: ViewportHandle;
    } | null>(null);
    const [fatal, setFatal] = React.useState<MessageKey | null>(null);
    /** 角上那个坐标轴控件和渲染循环之间的两根线。**用 ref 不用 state** —— 朝向每帧都在变,
     *  而这两个东西本身从头到尾是同一个。 */
    const orientationListener = React.useRef<((o: Orientation) => void) | null>(null);
    const lookAlongAxis = React.useRef<((axis: AxisName, sign: 1 | -1) => void) | null>(null);
    const subscribeOrientation = React.useCallback(
      (listener: (o: Orientation) => void) => {
        orientationListener.current = listener;
        return () => {
          orientationListener.current = null;
        };
      },
      [],
    );
    const pickAxis = React.useCallback(
      (axis: AxisName, sign: 1 | -1) => lookAlongAxis.current?.(axis, sign),
      [],
    );
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
        setFatal("sceneViewportWebglFailed");
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
      let SUN_DIRECTION = new THREE.Vector3(...sunDirection(35, 55));
      /** 点光源的阴影是六个面,一盏就抵得上好几盏平行光。场景允许 500 个物体,不封顶的话
       *  一屋子灯能把帧率拖到个位数,而**第五盏灯的影子对画面几乎没有贡献**。
       *  按场景里的先后取前几盏 —— 顺序是用户自己排的,比"随便挑几盏"讲得通。 */
      const SHADOW_CASTING_LIGHTS = 4;
      const capLightShadows = () => {
        let remaining = SHADOW_CASTING_LIGHTS;
        // 藏起来的灯不照明(渲染器跳过不可见节点),也就不该占掉一个投影名额。
        root.traverse((node) => {
          if (node instanceof THREE.PointLight) node.castShadow = false;
        });
        root.traverseVisible((node) => {
          if (node instanceof THREE.PointLight) node.castShadow = remaining-- > 0;
        });
      };
      /** 平行光的阴影相机是个正交盒子,默认 ±5 —— 展厅那种二十来米的场景一出盒子就没影子。
       *  所以每次场景或打光变了都按包围球重新框一次:方向来自场景数据,这里只把光挪到罩得住
       *  的位置,再把盒子放到刚好包住。 */
      const fitShadow = () => {
        const light = latest.current.content.lighting;
        if (light) SUN_DIRECTION = new THREE.Vector3(...sunDirection(light.azimuth, light.elevation));
        const bounds = visibleBounds(root);
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
      // 着色器网格,没有边(见 infiniteGrid)。此前是一块写死 40 米的 GridHelper:到 ±20 米
      // 就断出一条直边,而轨道控制允许拉到 1000 米 —— 飞出二十米之后地面参照直接没了。
      const grid = createInfiniteGrid();
      scene.add(grid.object);
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
        /** 选中的那个此刻该不该画选中框、挂操纵器 —— 藏起来的(或在藏起来的组里的)不挂:
         *  框住一片空气、拖一个看不见的东西,都比"选中了但没反应"更让人糊涂。 */
        selectionShown = false,
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
          latest.current.onError(errorText(e));
      };
      const loadModel = (id: string) => {
        if (!models.has(id)) {
          const promise = readSceneModel(props.workspace, id, abort.signal)
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
        selectionShown = !!o && shownInTree(o, root);
        if (o && selectionShown && !p.preview && !p.observing) transform.attach(o);
        else transform.detach();
        transform.setMode(p.mode);
        transform.setTranslationSnap(p.snap ? 0.25 : null);
        transform.setRotationSnap(p.snap ? Math.PI / 12 : null);
        transform.setScaleSnap(p.snap ? 0.1 : null);
        selection.visible = selectionShown && !p.preview && !p.observing;
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
      /** 把相机朝向交给角上那个坐标轴控件。**只在真的转了才通知** —— 每帧 setState 会让那棵
       *  小树每秒重渲六十次,而绝大多数帧里相机根本没动。阈值取一个肉眼看不出的角度。 */
      const lastOrientation = new THREE.Quaternion();
      const spareOrientation = new THREE.Quaternion();
      let orientationPrimed = false;
      function publishOrientation(camera: THREE.Camera) {
        const listener = orientationListener.current;
        if (!listener) return;
        camera.getWorldQuaternion(spareOrientation);
        // 点积接近 ±1 就是"几乎没转"。取绝对值:四元数的 q 和 -q 是同一个朝向。
        if (orientationPrimed && Math.abs(spareOrientation.dot(lastOrientation)) > 0.99999) return;
        orientationPrimed = true;
        lastOrientation.copy(spareOrientation);
        listener([spareOrientation.x, spareOrientation.y, spareOrientation.z, spareOrientation.w]);
      }
      /** 点了轴柄:站到目标的那一侧,**距离不变**。和工具栏「视角」里那几档同一条路。 */
      lookAlongAxis.current = (axis: AxisName, sign: 1 | -1) => {
        const observing = !!latest.current.observing;
        const controls = observing ? observerOrbit : orbit;
        const camera = observing ? observerCamera : editorCamera;
        const target = controls.target.clone();
        const distance = Math.max(5, camera.position.distanceTo(target));
        const [x, y, z] = axisVector(axis, sign);
        const direction = new THREE.Vector3(x, y, z);
        // 正对上/下看时相机的上方向退化(「哪边是上」没有定义,画面会莫名其妙地转),
        // 给一点偏置把它定住 —— 和工具栏的「顶视」用的是同一个办法。
        if (Math.abs(y) > 0.999) direction.z += 0.001;
        controls.update();
        camera.position.copy(target).addScaledVector(direction.normalize(), distance);
        controls.update();
      };
      let lastPath = "",
        observedShot = "";
      function frameOverview(
        direction: "perspective" | "front" | "top" = "perspective",
      ) {
        const bounds = visibleBounds(root);
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
        grid.object.visible = !p.preview;
        if (path) path.visible = !!p.observing;
        observer.group.visible = !!p.observing;
        transform.enabled = !p.preview && !p.observing;
        transform.getHelper().visible = transform.enabled && !!transform.object;
        selection.visible = selectionShown && !p.preview && !p.observing;
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
        //
        // **藏起来的相机在编辑视角里也不画**,但它照样能当机位:镜头看的是相机物体的数据
        // (`frameAt`),不是这个道具。此前这里只按视图切,一台藏起来的相机每帧又被设回可见 ——
        // 看得见、也点得中。而且只扫了顶层,组里的相机在镜头画面里一直露着。
        for (const node of objects.values())
          if (node.userData.editorOnly) node.visible = !p.preview && !node.userData.hidden;
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
          const viewing = p.observing ? observerCamera : editorCamera;
          // 换档和淡出都按"相机离地多远"算,所以每帧都要交给它当前的机位。
          grid.update(viewing);
          publishOrientation(viewing);
          renderer.render(scene, viewing);
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
            grid.object.visible = false;
            if (path) path.visible = false;
            observer.group.visible = false;
            renderer.render(scene, shootingCamera);
            renderer.setScissorTest(false);
          }
        }
      }
      function output(shot: SceneShot, clay = false) {
        if (modelsPending) throw new Error(translate.current("sceneModelsLoadingExport"));
        if (
          latest.current.content.objects.some(
            (o) => o.model_id && failedModels.has(o.model_id),
          )
        )
          throw new Error(translate.current("sceneModelsFailedExport"));
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
          // 聚焦全部只框看得见的;聚焦某一个时照它自己框 —— 选中一个藏起来的物体再按 F,
          // 用户要的是"它在哪",而不是"什么都不做"。
          const b = target === root ? visibleBounds(root) : new THREE.Box3().setFromObject(target);
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
                (b) => (b ? resolve(b) : reject(new Error(translate.current("sceneExportImageFailed")))),
                "image/png",
              ),
            );
          } finally {
            r.dispose();
          }
        },
        glb: async () => {
          if (modelsPending) throw new Error(translate.current("sceneModelsLoading"));
          if (
            latest.current.content.objects.some(
              (o) => o.model_id && failedModels.has(o.model_id),
            )
          )
            throw new Error(translate.current("sceneModelsFailedExport"));
          const data = await new GLTFExporter().parseAsync(cloneSceneForExport(root), {
            binary: true,
          });
          if (!(data instanceof ArrayBuffer)) throw new Error(translate.current("sceneExportGlbFailed"));
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
              translate.current,
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
          if (!type) throw new Error(translate.current("sceneVideoExportUnsupported"));
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
                reject(new Error(translate.current("sceneExportCancelled")));
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
                reject(new Error(translate.current("sceneVideoRecordFailed")));
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
        grid.dispose();
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
      <div className="scene-viewport" ref={host} aria-label={t("sceneViewport")}>
        {/* 出片预览时不显示:那一格画的是成片,控件属于编辑器。 */}
        {!props.preview && !fatal && (
          <SceneAxisGizmo subscribe={subscribeOrientation} onPick={pickAxis} />
        )}
        {props.observing && !fatal && (
          <>
            <div className="scene-motion-legend">
              <span />
              {t("sceneMotionLegend")}<small>{t("sceneMotionLegendHint")}</small>
            </div>
            <button
              className="scene-camera-inset"
              style={inset}
              aria-label={t("sceneCameraInsetEnlarge")}
              onClick={props.onCameraView}
            >
              <span>
                {t("sceneCameraInset")} <small>{props.time.toFixed(1)} s ↗</small>
              </span>
            </button>
          </>
        )}
        {fatal && (
          <div className="scene-empty" role="alert">
            {t(fatal)}
          </div>
        )}
      </div>
    );
  },
);
