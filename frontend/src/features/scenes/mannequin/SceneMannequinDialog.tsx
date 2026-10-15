import React from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { PersonStanding, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { assetKeys } from "@/api/queryKeys";
import { importAsset, type Asset } from "@/api/domains/assets";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Pick } from "../SceneControls";
import {
  applyPose,
  createMannequin,
  readPose,
  resetPose,
  type MannequinJoint,
  type MannequinRig,
} from "./mannequinRig";
import { MANNEQUIN_POSES, MANNEQUIN_POSE_ORDER } from "./mannequinPoses";
import {
  renderMannequinSnapshot,
  type MannequinSnapshotSize,
} from "./mannequinSnapshot";

/** 关节名 → 文案键。读数条上给「左前臂」这样的名字,不给内部键名。 */
const JOINT_LABELS: Record<MannequinJoint, MessageKey> = {
  hips: "sceneMannequinJointHips",
  spine: "sceneMannequinJointSpine",
  chest: "sceneMannequinJointChest",
  neck: "sceneMannequinJointNeck",
  head: "sceneMannequinJointHead",
  shoulderL: "sceneMannequinJointShoulderL",
  upperArmL: "sceneMannequinJointUpperArmL",
  forearmL: "sceneMannequinJointForearmL",
  handL: "sceneMannequinJointHandL",
  shoulderR: "sceneMannequinJointShoulderR",
  upperArmR: "sceneMannequinJointUpperArmR",
  forearmR: "sceneMannequinJointForearmR",
  handR: "sceneMannequinJointHandR",
  thighL: "sceneMannequinJointThighL",
  shinL: "sceneMannequinJointShinL",
  footL: "sceneMannequinJointFootL",
  thighR: "sceneMannequinJointThighR",
  shinR: "sceneMannequinJointShinR",
  footR: "sceneMannequinJointFootR",
};

/** 姿势预设键 → 文案键,顺序即「姿势预设」下拉里的顺序。 */
const POSE_LABELS: Record<(typeof MANNEQUIN_POSE_ORDER)[number], MessageKey> = {
  stand: "sceneMannequinPoseStand",
  walk: "sceneMannequinPoseWalk",
  sit: "sceneMannequinPoseSit",
  squat: "sceneMannequinPoseSquat",
  armsUp: "sceneMannequinPoseArmsUp",
};

/**
 * 摆姿势的人偶:一个自带视口的弹窗。**FK 摆姿势 → 着色快照 → 素材库 → 生图参考图**的最小闭环。
 *
 * - 点选一个关节(射线拾取 limb mesh),TransformControls 切成 rotate 挂到那个 pivot 上,
 *   拖圆环 = 转这个关节;子层级挂在 pivot 下,天然跟随(见 mannequinRig 的层级约定)。
 * - 姿势预设是一张关节角度表(见 mannequinPoses),一键覆盖当前姿势。
 * - 「存为素材」用离屏渲染出干净底、紧框的 PNG(见 mannequinSnapshot),`importAsset` 进素材库,
 *   生图节点的「要模型看的图片」(`image_asset_ids`)就能引用它。
 * - 「去生图」先存快照,再交给外层(SceneStudio.bridgeMannequin)开一张带这张参考图的画板。
 */
export function SceneMannequinDialog({
  workspaceId,
  open,
  onClose,
  onBridgeToBoard,
}: {
  workspaceId: string;
  open: boolean;
  onClose: () => void;
  /** 快照已入库后,把它带去生图(外层开画板)。 */
  onBridgeToBoard: (asset: Asset) => Promise<void>;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const host = React.useRef<HTMLDivElement>(null);
  /** 视口渲染循环只认 ref;选择/读数用 state 驱动界面。 */
  const rigRef = React.useRef<MannequinRig | null>(null);
  const [fatal, setFatal] = React.useState(false);
  const [joint, setJoint] = React.useState<MannequinJoint | null>(null);
  const [rotation, setRotation] = React.useState<[number, number, number]>([0, 0, 0]);
  const [pose, setPose] = React.useState<string>("stand");
  const [size, setSize] = React.useState<MannequinSnapshotSize>("square");
  const [busy, setBusy] = React.useState<"" | "snapshot" | "bridge">("");

  // 每次打开都是一尊新的人偶:界面状态跟着归零(不然下拉里写着「坐」、人偶站着)。
  React.useEffect(() => {
    if (!open) return;
    setJoint(null);
    setRotation([0, 0, 0]);
    setPose("stand");
    setFatal(false);
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFatal(true);
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    element.append(renderer.domElement);

    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8578, 1.3));
    const sun = new THREE.DirectionalLight(0xfff6ea, 2.2);
    sun.position.set(2.4, 3.4, 2.2);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.02;
    scene.add(sun, sun.target);
    const fill = new THREE.DirectionalLight(0xdfe8ff, 0.7);
    fill.position.set(-2.6, 1.6, 2);
    scene.add(fill);
    // 地面只接影子(ShadowMaterial),不画面 —— 摆姿势时给个"踩在地上"的参照。
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(2.5, 48),
      new THREE.ShadowMaterial({ opacity: 0.28 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 100);
    camera.position.set(1.7, 1.5, 2.7);
    const orbit = new OrbitControls(camera, renderer.domElement);
    orbit.target.set(0, 0.9, 0);
    orbit.enableDamping = true;
    orbit.minDistance = 0.4;
    orbit.maxDistance = 20;

    const rig = createMannequin();
    scene.add(rig.root);
    rigRef.current = rig;

    // 选中标记:一颗线框小球,每帧贴到选中 pivot 的世界位置上。
    const marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.05, 16, 12),
      new THREE.MeshBasicMaterial({
        color: 0x8da9cf,
        wireframe: true,
        transparent: true,
        opacity: 0.95,
        depthTest: false,
      }),
    );
    marker.renderOrder = 10;
    marker.visible = false;
    scene.add(marker);

    const transform = new TransformControls(camera, renderer.domElement);
    transform.setMode("rotate");
    transform.setSpace("local");
    scene.add(transform.getHelper());
    // 渲染循环活在 effect 闭包里,读不到最新的 React state —— 选中关节走 ref。
    const selected: { current: MannequinJoint | null } = { current: null };
    const select = (next: MannequinJoint | null) => {
      selected.current = next;
      setJoint(next);
      const pivot = next ? rig.joints.get(next)! : null;
      if (pivot && !transform.dragging) transform.attach(pivot);
      else if (!pivot) transform.detach();
      marker.visible = !!pivot;
    };
    transform.addEventListener("dragging-changed", (event) => {
      orbit.enabled = !event.value;
      // 松手才更新读数:拖动途中每帧 setState,读数会跳得没法看。
      if (!event.value && transform.object)
        setRotation([
          THREE.MathUtils.radToDeg(transform.object.rotation.x),
          THREE.MathUtils.radToDeg(transform.object.rotation.y),
          THREE.MathUtils.radToDeg(transform.object.rotation.z),
        ]);
    });

    // 点选关节:位移 < 4px 的左键点击才算,拖视角不误选。
    let down = { x: 0, y: 0 };
    const pointerDown = (e: PointerEvent) => {
      down = { x: e.clientX, y: e.clientY };
    };
    const pointerUp = (e: PointerEvent) => {
      if (
        transform.axis ||
        e.button !== 0 ||
        Math.hypot(e.clientX - down.x, e.clientY - down.y) > 4
      )
        return;
      const rect = renderer.domElement.getBoundingClientRect();
      const ray = new THREE.Raycaster();
      ray.setFromCamera(
        new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          (-(e.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      const hit = ray.intersectObjects(rig.meshes, false)[0];
      select(hit ? rig.jointOf(hit.object) : null);
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointerup", pointerUp);

    const resize = new ResizeObserver(() => {
      const w = element.clientWidth,
        h = element.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    resize.observe(element);

    let alive = true,
      frame = 0;
    const world = new THREE.Vector3();
    const render = () => {
      if (!alive) return;
      frame = requestAnimationFrame(render);
      orbit.update();
      if (selected.current && rig.joints.has(selected.current)) {
        rig.joints.get(selected.current)!.getWorldPosition(world);
        marker.position.copy(world);
      }
      renderer.render(scene, camera);
    };
    render();

    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      resize.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      transform.detach();
      transform.dispose();
      orbit.dispose();
      ground.geometry.dispose();
      (ground.material as THREE.Material).dispose();
      marker.geometry.dispose();
      (marker.material as THREE.Material).dispose();
      rig.dispose();
      rigRef.current = null;
      renderer.dispose();
      renderer.domElement.remove();
    };
    // 视口整套生命周期跟着弹窗开关走;joint/pose 只是界面读数,不进依赖。
  }, [open]);

  /** 按当前姿势出快照并入库;成功返回素材,失败已 toast。调用处管 busy。 */
  async function saveSnapshot(): Promise<Asset | null> {
    const rig = rigRef.current;
    if (!rig) return null;
    try {
      const blob = await renderMannequinSnapshot(rig.root, size);
      const asset = await importAsset({
        workspaceId,
        file: new File([blob], `${t("sceneMannequinFileName")}-${Date.now()}.png`, {
          type: "image/png",
        }),
      });
      await qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      toast.success(t("sceneMannequinSnapshotSaved"));
      return asset;
    } catch (e) {
      toast.error(errorText(e));
      return null;
    }
  }

  async function snapshot() {
    if (busy) return;
    setBusy("snapshot");
    try {
      await saveSnapshot();
    } finally {
      setBusy("");
    }
  }

  async function bridge() {
    if (busy) return;
    setBusy("bridge");
    try {
      const asset = await saveSnapshot();
      if (asset) await onBridgeToBoard(asset);
    } finally {
      setBusy("");
    }
  }

  function pickPose(next: string) {
    setPose(next);
    const rig = rigRef.current;
    const preset = MANNEQUIN_POSES[next];
    if (!rig || !preset) return;
    resetPose(rig);
    applyPose(rig, preset);
    // 读数跟着预设走。
    if (joint) {
      const [x, y, z] = readPose(rig)[joint];
      setRotation([x, y, z]);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!next && !busy ? onClose() : undefined)}>
      <DialogContent
        className="mannequin-dialog w-[min(76rem,calc(100vw-2rem))]"
        aria-label={t("sceneMannequinTitle")}
      >
        <div className="flex min-h-0 flex-col gap-4">
          <div>
            <DialogTitle>{t("sceneMannequinTitle")}</DialogTitle>
            <DialogDescription>{t("sceneMannequinBody")}</DialogDescription>
          </div>
          <div className="flex min-h-0 flex-col gap-4 lg:flex-row">
            <div
              ref={host}
              className="mannequin-viewport relative h-[52vh] min-h-72 min-w-0 flex-1 overflow-hidden rounded-lg border"
              aria-label={t("sceneMannequinViewport")}
            >
              {fatal && (
                <div className="scene-empty" role="alert">
                  {t("sceneViewportWebglFailed")}
                </div>
              )}
            </div>
            <div className="flex w-full shrink-0 flex-col gap-3 lg:w-60">
              <Pick
                label={t("sceneMannequinPosePreset")}
                value={pose}
                options={MANNEQUIN_POSE_ORDER.map(
                  (key): [string, string] => [key, t(POSE_LABELS[key])],
                )}
                onChange={pickPose}
                size="sm"
              />
              <Pick
                label={t("sceneMannequinSize")}
                value={size}
                options={[
                  ["square", t("sceneMannequinSizeSquare")],
                  ["portrait", t("sceneMannequinSizePortrait")],
                ]}
                onChange={(next) => setSize(next as MannequinSnapshotSize)}
                size="sm"
              />
              <div className="mannequin-readout">
                <PersonStanding size={14} aria-hidden="true" />
                <span>
                  {joint
                    ? `${t(JOINT_LABELS[joint])} · ${rotation.map((a) => `${Math.round(a)}°`).join(" ")}`
                    : t("sceneMannequinNoJoint")}
                </span>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={!!busy}
                onClick={() => {
                  const rig = rigRef.current;
                  if (!rig) return;
                  resetPose(rig);
                  setRotation([0, 0, 0]);
                }}
              >
                <RotateCcw />
                {t("sceneMannequinReset")}
              </Button>
              <div className="mt-auto flex flex-col gap-2">
                <Button
                  variant="outline"
                  loading={busy === "snapshot"}
                  disabled={!!busy}
                  onClick={() => void snapshot()}
                >
                  {t("sceneMannequinSnapshot")}
                </Button>
                <Button
                  loading={busy === "bridge"}
                  disabled={!!busy}
                  onClick={() => void bridge()}
                >
                  {t("sceneMannequinBridge")}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
