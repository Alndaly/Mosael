import React from "react";
import {
  Camera,
  ChevronRight,
  Play,
  Pause,
  RotateCw,
  MoveRight,
  Video,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { CameraFrame, SceneShot } from "@/api/domains/scenes";
import { Num, Pick, Vector } from "./SceneControls";
import { cameraPreset, sampleCamera } from "./sceneGraph";

export function SceneCameraPanel({
  shot,
  time,
  preview,
  playing,
  onPatch,
  onTime,
  onPreview,
  onPlaying,
  capture,
  observe,
  camera,
  onNext,
}: {
  shot: SceneShot;
  time: number;
  preview: boolean;
  playing: boolean;
  onPatch: (patch: Partial<SceneShot>) => void;
  onTime: (time: number) => void;
  onPreview: (value: boolean) => void;
  onPlaying: (value: boolean) => void;
  capture: (time: number) => void;
  observe: () => void;
  camera: () => CameraFrame;
  onNext: () => void;
}) {
  const current = sampleCamera(shot, time);
  const frameIndex = shot.frames.findIndex(
    (f) => Math.abs(f.time - time) < 0.001,
  );
  function patchFrame(patch: Partial<CameraFrame>) {
    if (frameIndex < 0 && shot.frames.length >= 100) return;
    onPatch({
      frames: [
        ...shot.frames.filter((_, i) => i !== frameIndex),
        { ...current, ...patch },
      ].sort((a, b) => a.time - b.time),
    });
  }
  function preset(kind: "orbit" | "push" | "still") {
    const first = { ...(preview ? current : camera()), time: 0 };
    onPatch(
      kind === "still"
        ? { frames: [first] }
        : cameraPreset({ ...shot, frames: [first] }, kind),
    );
    onTime(0);
    onPreview(true);
    onPlaying(false);
  }
  return (
    <div className="scene-camera-panel">
      <section className="scene-panel-heading">
        <h2>让镜头怎么走？</h2>
        <p>先在画面中找到喜欢的角度，再选择运镜方式。</p>
      </section>
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
              onPatch({
                duration,
                frames: shot.frames.map((f) => ({
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
        <Button
          variant="secondary"
          onClick={() => {
            onPreview(true);
            if (time >= shot.duration) onTime(0);
            onPlaying(!playing);
          }}
        >
          {playing ? <Pause size={15} /> : <Play size={15} />}{" "}
          {playing ? "暂停预览" : "播放镜头"}
        </Button>
      </section>
      <details className="scene-details scene-manual-camera">
        <summary>自己设置起点和终点</summary>
        <div>
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
        </div>
      </details>
      <details className="scene-details">
        <summary>镜头高级设置</summary>
        <div>
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
              variant="ghost"
              onClick={() =>
                onPatch({
                  frames: shot.frames.filter((_, i) => i !== frameIndex),
                })
              }
            >
              移除此途经点
            </Button>
          )}
        </div>
      </details>
      <div className="scene-side-next">
        <Button onClick={onNext}>
          下一步：生成视频
          <ChevronRight size={15} />
        </Button>
      </div>
    </div>
  );
}
