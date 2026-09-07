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
import React from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";
import {
  readSceneModel,
  type CameraFrame,
  type SceneContent,
  type SceneObject,
  type SceneShot,
  type Vec3,
} from "@/api/domains/scenes";
import { sampleCamera } from "./sceneGraph";

export type ViewportHandle = {
  camera: () => CameraFrame;
  focus: () => void;
  placement: (halfWidth: number) => Vec3;
  view: (direction: "perspective" | "front" | "top") => void;
  editCamera: (shot: SceneShot, time: number) => void;
  frame: (shot: SceneShot, time: number) => Promise<Blob>;
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
  if (o.kind === "light") {
    group.add(new THREE.PointLight(o.color, o.intensity, 50, 2));
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
function pose(camera: THREE.PerspectiveCamera, frame: CameraFrame) {
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
        frame: (s, t) => runtime.current!.handle.frame(s, t),
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
      element.append(renderer.domElement);
      const scene = new THREE.Scene(),
        root = new THREE.Group();
      scene.add(root);
      const ambient = new THREE.HemisphereLight(0xffffff, 0x666879, 1.5);
      scene.add(ambient);
      const sun = new THREE.DirectionalLight(0xffffff, 2.5);
      sun.position.set(4, 9, 5);
      scene.add(sun);
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
              new GLTFLoader().parseAsync(
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
                    child.geometry = child.geometry.clone();
                    child.material = Array.isArray(child.material)
                      ? child.material.map((m) => m.clone())
                      : child.material.clone();
                  }
                });
                node.add(copy);
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
        for (const point of shotPathPoints(latest.current.shot))
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
        const signature = JSON.stringify([
          p.shot.frames,
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
            new THREE.BufferGeometry().setFromPoints(shotPathPoints(p.shot)),
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
          frame = sampleCamera(p.shot, p.time);
        shootingCamera.aspect = aspect;
        pose(shootingCamera, frame);
        observer.update(frame, aspect);
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
      function output(shot: SceneShot) {
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
        const aspect = aspectRatio(shot);
        r.setSize(
          aspect >= 1 ? 1280 : 720,
          Math.round((aspect >= 1 ? 1280 : 720) / aspect),
        );
        const exportScene = new THREE.Scene();
        exportScene.background = new THREE.Color(
          latest.current.content.background,
        );
        const copy = root.clone(true);
        exportScene.add(copy, ambient.clone(), sun.clone());
        const camera = new THREE.PerspectiveCamera(45, aspect, 0.05, 2000);
        return {
          r,
          draw: (time: number) => {
            pose(camera, sampleCamera(shot, time));
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
          const frame = sampleCamera(shot, time);
          orbit.update();
          pose(editorCamera, frame);
          orbit.target.fromArray(frame.target);
          orbit.update();
        },
        frame: async (shot, time) => {
          const { r, draw } = output(shot);
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
          const data = await new GLTFExporter().parseAsync(root, {
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
