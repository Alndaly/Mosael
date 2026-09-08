import React from "react";
import { SceneSubsection } from "./SceneSubsection";
import { Camera, RotateCw, MoveRight, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Keyframe, SceneObject, SceneShot, Vec3 } from "@/api/domains/scenes";
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
  capture,
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
  capture: (time: number) => void;
  observe: () => void;
  camera: () => { position: Vec3; target: Vec3; fov: number };
}) {
  const current = sampleCamera(rig, shot, time);
  const frameIndex = rig.track.findIndex((f) => Math.abs(f.time - time) < 0.001);
  /**
   * 改这一刻的机位。
   *
   * **轨是空的时候改的是静止姿态**,不是"插入第一个关键帧" —— 一台不动的相机不该因为你调了
   * 一下位置就突然有了动画。要动画得先选一种运镜,或者在别的时刻记一个视角。
   */
  function patchFrame(patch: Partial<Keyframe>) {
    if (!rig.track.length) {
      const next = { ...current, ...patch };
      onRig({
        position: next.position,
        target: next.target ?? current.target,
        fov: next.fov ?? current.fov,
      });
      return;
    }
    if (frameIndex < 0 && rig.track.length >= 100) return;
    onRig({
      track: [
        ...rig.track.filter((_, i) => i !== frameIndex),
        { ...current, ...patch },
      ].sort((a, b) => a.time - b.time),
    });
  }
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
  return (
    <div className="scene-camera-panel">
      <p className="scene-camera-hint">先在画面中找到喜欢的角度，再选择运镜方式。</p>
      <section className="scene-preset-list" aria-label="运镜方式">
        <button onClick={() => preset("orbit")}>
          <RotateCw size={19} />
          <span>
            <strong>围绕主体</strong>
            <small>以当前观察中心环绕一周</small>
          </span>
        </button>
        <button onClick={() => preset("push")}>
          <MoveRight size={19} />
          <span>
            <strong>缓缓推进</strong>
            <small>从当前视角靠近主体</small>
          </span>
        </button>
        <button onClick={() => preset("still")}>
          <Video size={19} />
          <span>
            <strong>固定镜头</strong>
            <small>保持当前构图不移动</small>
          </span>
        </button>
        <p>选择后会替换当前镜头的运镜，可撤销。</p>
      </section>
      <section className="scene-camera-settings">
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
      </section>
      {/* 两段折叠收在一个 stack 里。**分割线是每一行自己的上边框**,所以行与行之间不能再叠
          外层容器那 16px 的 gap —— 叠了之后线上方 28px、下方 12px,线看着黏在下面那行上。 */}
      <div className="scene-detail-stack">
        <SceneSubsection title="自己设置起点和终点">
          <p>在编辑视角中调整构图，分别记下镜头从哪里开始、在哪里结束。</p>
          {preview && (
            <Button variant="secondary" onClick={observe}>
              <Camera size={15} />
              从当前镜头继续调整
            </Button>
          )}
          <div className="scene-shape">
            <Button
              variant="secondary"
              disabled={preview}
              onClick={() => capture(0)}
            >
              设为起点
            </Button>
            <Button
              variant="secondary"
              disabled={preview}
              onClick={() => capture(shot.duration)}
            >
              设为终点
            </Button>
          </div>
          <p>在底部时间条选择中间时刻，再点「记录此视角」可增加途经点。</p>
        </SceneSubsection>
      <SceneSubsection title="镜头高级设置">
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
            onChange={(fov) => patchFrame({ fov })}
          />
          <Pick
            label="镜头速度变化"
            value={shot.easing}
            options={[
              ["smooth", "开始和结束时缓慢"],
              ["linear", "全程保持匀速"],
            ]}
            onChange={(easing) =>
              onPatch({ easing: easing as SceneShot["easing"] })
            }
          />
          <p>当前时刻 {time.toFixed(1)} 秒。修改坐标会设置该时刻的途经点。</p>
          <Vector
            label="相机位置"
            value={current.position}
            onChange={(position) => patchFrame({ position })}
          />
          <Vector
            label="注视位置"
            value={current.target}
            onChange={(target) => patchFrame({ target })}
          />
          {frameIndex > 0 && (
            <Button
              variant="outline"
              onClick={() =>
                onRig({ track: rig.track.filter((_, i) => i !== frameIndex) })
              }
            >
              移除此途经点
            </Button>
          )}
        </SceneSubsection>
      </div>
    </div>
  );
}
