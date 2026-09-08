import React from "react";
import { SceneSubsection } from "./SceneSubsection";
import { Camera, RotateCw, MoveRight, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SceneObject, SceneShot, Vec3 } from "@/api/domains/scenes";
import { Num, Pick, Vector } from "./SceneControls";
import { cameraPreset, sampleCamera } from "./sceneGraph";

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
      <p className="scene-camera-hint">先在画面中找到喜欢的角度，再选择运镜方式。</p>
      {/* **三档运镜不再各自装一个框。** 它们是一组同类选项,不是三张卡片 —— 三个边框
          在一栏里就是三个方块,而框本身没有携带任何信息(哪个能点?三个都能)。
          现在只有 hover 时才有底,和右栏别处的列表行同一套反应。 */}
      <section className="scene-preset-list" aria-label="运镜方式">
        <button onClick={() => preset("orbit")}>
          <RotateCw size={17} />
          <span>
            <strong>围绕主体</strong>
            <small>以当前观察中心环绕一周</small>
          </span>
        </button>
        <button onClick={() => preset("push")}>
          <MoveRight size={17} />
          <span>
            <strong>缓缓推进</strong>
            <small>从当前视角靠近主体</small>
          </span>
        </button>
        <button onClick={() => preset("still")}>
          <Video size={17} />
          <span>
            <strong>固定镜头</strong>
            <small>保持当前构图不移动</small>
          </span>
        </button>
        <p>选择后会替换当前镜头的运镜，可撤销。</p>
      </section>
      <div className="scene-shape">
        <Num
          label="时长（秒）"
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
          <span>画面比例</span>
          <Pick
            label="画面比例"
            value={shot.aspect}
            options={[
              ["16:9", "横屏 16:9"],
              ["9:16", "竖屏 9:16"],
              ["1:1", "方形 1:1"],
            ]}
            onChange={(aspect) =>
              onPatch({ aspect: aspect as SceneShot["aspect"] })
            }
          />
        </label>
      </div>
      <SceneSubsection expanded title="机位构图">
        <Button variant="outline" disabled={preview} onClick={applyView}>
          <Camera size={15} />将当前视角应用到机位
        </Button>
        {preview && <Button variant="outline" onClick={observe}><Camera size={15} />从当前镜头继续调整</Button>}
        <p>先在时间线上选择时刻，再调整机位，按 I 插入关键帧。切换时刻前请记录需要保留的姿态。</p>
      </SceneSubsection>
      <SceneSubsection expanded title="镜头高级设置">
        <label className="scene-number">
          <span>镜头名称</span>
          <Input
            aria-label="镜头名称"
            value={shot.name}
            maxLength={160}
            onChange={(e) => onPatch({ name: e.target.value })}
          />
        </label>
        <Num
          label="视角（广角 / 长焦）"
          value={current.fov}
          min={10}
          max={120}
          step={1}
          onChange={(fov) => onPose({ fov })}
        />
        <Pick
          label="镜头速度变化"
          value={shot.easing}
          options={[
            ["smooth", "开始和结束时缓慢"],
            ["linear", "全程保持匀速"],
          ]}
          onChange={(easing) => onPatch({ easing: easing as SceneShot["easing"] })}
        />
        <p>当前时刻 {time.toFixed(1)} 秒。修改后按 I 插入关键帧。</p>
        <Vector
          label="相机位置"
          value={current.position}
          onChange={(position) => onPose({ position })}
        />
        <Vector
          label="注视位置"
          value={current.target}
          onChange={(target) => onPose({ target })}
        />
      </SceneSubsection>
    </>
  );
}
