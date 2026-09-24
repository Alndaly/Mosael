import React from "react";
import { SceneSubsection } from "./SceneSubsection";
import { Camera, RotateCw, MoveRight, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SceneObject, SceneShot, Vec3 } from "@/api/domains/scenes";
import { Num, Pick, Vector } from "./SceneControls";
import { cameraPreset, sampleCamera } from "./sceneGraph";
import { useI18n } from "@/app/preferences";

export function SceneCameraPanel({
  shot,
  rig,
  time,
  preview,
  onPatch,
  onRig,
  onTime,
  onPreview,
  onPlaying,
  applyView,
  onPose,
  pose,
  observe,
  camera,
}: {
  shot: SceneShot;
  /** 拍这个镜头的那台机位 —— **运镜长在它身上**,不在镜头上。 */
  rig: SceneObject;
  time: number;
  preview: boolean;
  onPatch: (patch: Partial<SceneShot>) => void;
  onRig: (patch: Partial<SceneObject>) => void;
  onTime: (time: number) => void;
  onPreview: (value: boolean) => void;
  onPlaying: (value: boolean) => void;
  pose?: Pick<SceneObject, "position" | "target" | "fov">;
  applyView: () => void;
  onPose: (patch: Partial<Pick<SceneObject, "position" | "target" | "fov">>) => void;
  observe: () => void;
  camera: () => { position: Vec3; target: Vec3; fov: number };
}) {
  const t = useI18n();
  const current = pose ?? sampleCamera(rig, shot, time);
  function preset(kind: "orbit" | "push" | "still") {
    const from = preview ? current : camera();
    const rest = { position: from.position, target: from.target, fov: from.fov };
    // 「固定机位」= 没有轨。此前它是"一条只有一帧的轨",而"有没有轨"本该正好等于"动不动"。
    onRig(
      kind === "still"
        ? { ...rest, track: [] }
        : { ...rest, track: cameraPreset({ ...rig, ...rest }, shot, kind) },
    );
    onTime(0);
    onPreview(true);
    onPlaying(false);
  }
  //: 外壳、左右内距、竖向节奏全归 ScenePanel(见 .scene-panel-body)—— 这里只出内容。
  //: 此前它自己写了一套 `padding: 16px`,于是它的左边缘和上面那节物体列表对不齐。
  return (
    <>
      <p className="scene-camera-hint">{t("sceneCameraHint")}</p>
      {/* **三档运镜不再各自装一个框。** 它们是一组同类选项,不是三张卡片 —— 三个边框
          在一栏里就是三个方块,而框本身没有携带任何信息(哪个能点?三个都能)。
          现在只有 hover 时才有底,和右栏别处的列表行同一套反应。 */}
      <section className="scene-preset-list" aria-label={t("sceneCameraMoves")}>
        <button onClick={() => preset("orbit")}>
          <RotateCw size={17} />
          <span>
            <strong>{t("sceneCameraOrbit")}</strong>
            <small>{t("sceneCameraOrbitHint")}</small>
          </span>
        </button>
        <button onClick={() => preset("push")}>
          <MoveRight size={17} />
          <span>
            <strong>{t("sceneCameraPush")}</strong>
            <small>{t("sceneCameraPushHint")}</small>
          </span>
        </button>
        <button onClick={() => preset("still")}>
          <Video size={17} />
          <span>
            <strong>{t("sceneCameraStill")}</strong>
            <small>{t("sceneCameraStillHint")}</small>
          </span>
        </button>
        <p>{t("sceneCameraMovesNote")}</p>
      </section>
      <div className="scene-shape">
        <Num
          label={t("sceneShotDuration")}
          value={shot.duration}
          min={0.1}
          max={120}
          onChange={(duration) => {
            // 改时长要把轨上的时刻**按比例缩放**,否则运镜的后半段会掉到镜头之外。
            onPatch({ duration });
            if (rig.track.length)
              onRig({
                track: rig.track.map((f) => ({
                  ...f,
                  time: (f.time / shot.duration) * duration,
                })),
              });
            onTime(0);
            onPlaying(false);
          }}
        />
        <label className="scene-number">
          <span>{t("sceneShotAspect")}</span>
          <Pick
            label={t("sceneShotAspect")}
            value={shot.aspect}
            options={[
              ["16:9", t("sceneAspectLandscape")],
              ["9:16", t("sceneAspectPortrait")],
              ["1:1", t("sceneAspectSquare")],
            ]}
            onChange={(aspect) =>
              onPatch({ aspect: aspect as SceneShot["aspect"] })
            }
          />
        </label>
      </div>
      <SceneSubsection expanded title={t("sceneCameraFraming")}>
        <Button variant="outline" disabled={preview} onClick={applyView}>
          <Camera size={15} />{t("sceneCameraApplyView")}
        </Button>
        {preview && <Button variant="outline" onClick={observe}><Camera size={15} />{t("sceneCameraContinue")}</Button>}
        <p>{t("sceneCameraFramingHint")}</p>
      </SceneSubsection>
      <SceneSubsection expanded title={t("sceneCameraAdvanced")}>
        <label className="scene-number">
          <span>{t("sceneShotNameLabel")}</span>
          <Input
            aria-label={t("sceneShotNameLabel")}
            value={shot.name}
            maxLength={160}
            onChange={(e) => onPatch({ name: e.target.value })}
          />
        </label>
        <Num
          label={t("sceneCameraFov")}
          value={current.fov}
          min={10}
          max={120}
          step={1}
          onChange={(fov) => onPose({ fov })}
        />
        <Pick
          label={t("sceneShotEasing")}
          value={shot.easing}
          options={[
            ["smooth", t("sceneEasingSmooth")],
            ["linear", t("sceneEasingLinear")],
          ]}
          onChange={(easing) => onPatch({ easing: easing as SceneShot["easing"] })}
        />
        <p>{t("sceneCameraTimeHint").replace("{time}", time.toFixed(1))}</p>
        <Vector
          label={t("sceneCameraPosition")}
          value={current.position}
          onChange={(position) => onPose({ position })}
        />
        <Vector
          label={t("sceneCameraTarget")}
          value={current.target}
          onChange={(target) => onPose({ target })}
        />
      </SceneSubsection>
    </>
  );
}
