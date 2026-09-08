import React from "react";
import { Box, Video } from "lucide-react";

import type { SceneContent, SceneShot } from "@/api/domains/scenes";
import { trackRows } from "./sceneTracks";

/**
 * 关键帧视图(Dope Sheet):**按物体分行,横轴是时间**。
 *
 * 换掉此前那条只画「当前机位」的关键帧轨。那条的问题不是不好看,是**说不出整件事** ——
 * 场景里同时还有物体在走位,而它们和运镜共用同一条时间轴;只画相机的话,"第 3 秒人走到门口、
 * 同一刻镜头推进"这种关系在界面上根本没有位置可以表达,用户只能靠脑子对时间。
 *
 * 机位和物体**同列一张表**,只是机位排在第一行 —— 相机本来就是场景里的物体
 * (见 docs/design/scene-time-and-cameras.md),分成两个视图是在重新制造那条已经拆掉的界线。
 *
 * 时间滑块也在这张表里(第一行的"标尺"),而不是浮在表外:两者共用同一条横轴,共用才对得齐。
 * 分开放的话,名字列的宽度会让上面那条滑块和下面的菱形错开一整列 —— 而"位置即时间"一旦
 * 对不齐就不成立了。
 */
export function SceneDopeSheet({
  content,
  shot,
  time,
  selectedId,
  playing,
  onSeek,
  onSelect,
}: {
  content: SceneContent;
  shot: SceneShot;
  time: number;
  selectedId: string | null;
  playing: boolean;
  onSeek: (time: number) => void;
  onSelect: (id: string) => void;
}) {
  const rows = trackRows(content, shot, selectedId);
  const at = (value: number) => (shot.duration > 0 ? (value / shot.duration) * 100 : 0);
  /**
   * 在轨道上点一下 = 把时间拨到那儿。轨道本来就是一条标尺,点它却什么也不发生说不过去。
   *
   * 量的是**被点的那一条轨自己**。此前量的是标尺行那个 div —— 它们在同一栏、宽度一样,
   * 所以在浏览器里看不出区别,但那是巧合不是道理:标尺行将来多一个刻度、少一段内距,
   * 落点就整体偏了,而偏移只有在点击时才表现出来。
   */
  const seekFromPointer = (event: React.PointerEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    onSeek(Number((ratio * shot.duration).toFixed(2)));
  };

  return (
    <div className="scene-dope" role="group" aria-label={`${shot.name} 的关键帧`}>
      {/* 标尺行:名字列留空,滑块占满轨道列 —— 下面每一行的菱形和它同一条横轴。 */}
      <div className="scene-dope-ruler">
        <span />
        <div>
          <input
            aria-label="镜头时间"
            type="range"
            min={0}
            max={shot.duration}
            step={0.01}
            value={Math.min(time, shot.duration)}
            onChange={(event) => onSeek(Number(event.target.value))}
          />
        </div>
      </div>
      <div className="scene-dope-rows">
        {rows.map((row) => (
          <div
            className="scene-dope-row"
            key={row.object.id}
            data-selected={row.object.id === selectedId || undefined}
          >
            <button
              className="scene-dope-name"
              title={row.object.name}
              aria-pressed={row.object.id === selectedId}
              onClick={() => onSelect(row.object.id)}
            >
              {row.isRig ? <Video size={12} /> : <Box size={12} />}
              <span>{row.object.name}</span>
            </button>
            {/* 轨道本身可点:落点即时刻。菱形是它上面的标记,不是一排按钮 —— 所以整条轨
                只有一个交互目标,而菱形只负责"看得见"。 */}
            <div
              className="scene-dope-lane"
              role="presentation"
              onPointerDown={(event) => {
                event.preventDefault();
                onSelect(row.object.id);
                seekFromPointer(event);
              }}
            >
              {row.times.map((value) => (
                <i
                  key={value}
                  className="scene-dope-key"
                  style={{ left: `${at(value)}%` }}
                  data-edge={value === 0 ? "start" : value === shot.duration ? "end" : undefined}
                  data-here={Math.abs(value - time) < 0.05 || undefined}
                  title={`${row.object.name} · ${value.toFixed(1)}s`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      {/* 播放头贯穿所有行 —— 一条竖线把"此刻"和每一行的菱形对起来,这正是分行之后唯一
          还缺的那样东西。
          外面这层把百分比**锚在轨道列上**:直接挂在表上的话,百分比量的是含名字列的整宽,
          于是播放头会比同一时刻的菱形一路偏右。 */}
      <div className="scene-dope-playhead-area" aria-hidden>
        <i
          className="scene-dope-playhead"
          style={{ left: `${at(Math.min(time, shot.duration))}%` }}
          data-playing={playing || undefined}
        />
      </div>
    </div>
  );
}
