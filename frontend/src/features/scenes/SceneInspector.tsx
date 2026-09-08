import React from "react";
import { Clock, Copy, Group, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SceneContent, SceneLighting, SceneObject } from "@/api/domains/scenes";
import { CUSTOM_PRESET, presetById, presetGroups } from "./lighting";
import { Num, Vector, Tool } from "./SceneControls";
import { duplicateObject, groupTargets, makeObject, moveToGroup, removeObjects } from "./sceneGraph";
export function SceneInspector({
  content,
  object,
  time,
  objectPatch,
  update,
  setSelected,
}: {
  content: SceneContent;
  object: SceneObject | undefined;
  /** 当前时刻 —— 走位记在这一刻上。 */
  time: number;
  objectPatch: (id: string, patch: Partial<SceneObject>) => void;
  update: (c: SceneContent) => void;
  setSelected: (id: string | null) => void;
}) {
  //: 外壳和标题都归 ScenePanel —— 这里只出内容。此前它自己带 <aside> 和 <h2>,
  //: 于是右栏里出现"两层标题"和"两层边框"。
  return (
    <div className="scene-inspector">
      <section>
        {object ? (
          <>
            <Input
              aria-label="对象名称"
              value={object.name}
              maxLength={160}
              onChange={(e) => objectPatch(object.id, { name: e.target.value })}
            />
            {/* **「移到…」是「组」此前缺的那一半。** 数据模型一直支持 parent_id,但界面上没有
                任何入口能把已有的物体放进已有的组 —— 于是菜单里那个空组建完就废。
                选择器而不是拖拽:长列表 + 触控板上拖拽很难瞄准,而且选择器天生可键盘操作。 */}
            {!!groupTargets(content, object.id).length && (
              <label className="scene-number">
                <span>所属组</span>
                <Select
                  value={object.parent_id ?? TOP_LEVEL}
                  onValueChange={(value) =>
                    update(moveToGroup(content, object.id, value === TOP_LEVEL ? null : value))
                  }
                >
                  <SelectTrigger aria-label="所属组">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={TOP_LEVEL}>不在组里</SelectItem>
                    {groupTargets(content, object.id).map((group) => (
                      <SelectItem key={group.id} value={group.id}>
                        {group.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            )}
            {object.kind !== "camera" && (
              <ObjectTrackSection
                object={object}
                time={time}
                onPatch={(patch) => objectPatch(object.id, patch)}
              />
            )}
            <div className="scene-actions">
              <Tool
                label="复制对象"
                onClick={() => update(duplicateObject(content, object.id))}
              >
                <Copy size={15} />
              </Tool>
              <Tool
                label="编组对象"
                onClick={() => {
                  const group = makeObject("group", {
                    name: `${object.name} 组`,
                    parent_id: object.parent_id,
                  });
                  update({
                    ...content,
                    objects: [
                      ...content.objects.map((o) =>
                        o.id === object.id ? { ...o, parent_id: group.id } : o,
                      ),
                      group,
                    ],
                  });
                  setSelected(group.id);
                }}
              >
                <Group size={15} />
              </Tool>
              <Tool
                label="删除对象"
                onClick={() => {
                  update(removeObjects(content, [object.id]));
                  setSelected(null);
                }}
              >
                <Trash2 size={15} />
              </Tool>
              <button
                className="scene-text-button"
                onClick={() =>
                  objectPatch(object.id, { hidden: !object.hidden })
                }
              >
                {object.hidden ? "显示" : "隐藏"}
              </button>
            </div>
            {/* 相机没有形状,也没有颜色和材质 —— 它有的是视角。此前它跟着几何体一起显示
                「宽度/高度/深度/粗糙度/金属度」,那些字段对它一个都不成立。 */}
            {object.kind === "camera" && (
              <Num
                label="视角（越小越长焦）"
                caption="视角°"
                value={object.fov}
                min={10}
                max={120}
                step={1}
                onChange={(fov) => objectPatch(object.id, { fov })}
              />
            )}
            {!["model", "group", "light", "camera"].includes(object.kind) && (
              <div className="scene-shape">
                {(
                  [
                    "width",
                    "height",
                    "depth",
                    "radius",
                    "steps",
                    "door_width",
                    "door_height",
                  ] as const
                )
                  .filter((k) =>
                    k === "radius"
                      ? ["sphere", "cylinder"].includes(object.kind)
                      : k === "steps"
                        ? object.kind === "stairs"
                        : k.startsWith("door")
                          ? object.kind === "room"
                          : k === "height"
                            ? !["sphere", "plane"].includes(object.kind)
                            : !["sphere", "cylinder"].includes(object.kind),
                  )
                  .map((k) => (
                    <Num
                      key={k}
                      label={
                        // 人物那三个数叫"宽度/高度/深度"是对的但没用 —— 调的人想的是身高和
                        // 肩宽。名字贴着它实际是什么,省掉一次心里的换算。
                        PARAMETER_LABELS[object.kind]?.[k] ??
                        {
                          width: "宽度",
                          height: "高度",
                          depth: "深度",
                          radius: "半径",
                          steps: "阶数",
                          door_width: "门宽",
                          door_height: "门高",
                        }[k]
                      }
                      value={object.parameters[k]}
                      min={k === "steps" ? 1 : 0.1}
                      max={k === "steps" ? 64 : 100}
                      step={k === "steps" ? 1 : 0.1}
                      onChange={(n) =>
                        objectPatch(object.id, {
                          parameters: {
                            ...object.parameters,
                            [k]: k === "steps" ? Math.round(n) : n,
                          },
                        })
                      }
                    />
                  ))}
              </div>
            )}
            {!["group", "model", "camera"].includes(object.kind) && (
              <>
                <label className="scene-color">
                  颜色
                  <input
                    aria-label="对象颜色"
                    type="color"
                    value={object.color}
                    onChange={(e) =>
                      objectPatch(object.id, { color: e.target.value })
                    }
                  />
                </label>
                {object.kind === "light" ? (
                  <Num
                    label="光照强度"
                    value={object.intensity}
                    min={0}
                    max={10000}
                    onChange={(intensity) =>
                      objectPatch(object.id, { intensity })
                    }
                  />
                ) : (
                  <div className="scene-shape">
                    <Num
                      label="粗糙度"
                      value={object.roughness}
                      min={0}
                      max={1}
                      onChange={(roughness) =>
                        objectPatch(object.id, { roughness })
                      }
                    />
                    <Num
                      label="金属度"
                      value={object.metalness}
                      min={0}
                      max={1}
                      onChange={(metalness) =>
                        objectPatch(object.id, { metalness })
                      }
                    />
                  </div>
                )}
              </>
            )}
            <details className="scene-details">
              <summary>精确位置与旋转</summary>
              <div>
                {" "}
                <Vector
                  label="位置"
                  value={object.position}
                  onChange={(position) => objectPatch(object.id, { position })}
                />
                <Vector
                  label="旋转"
                  value={object.rotation}
                  onChange={(rotation) => objectPatch(object.id, { rotation })}
                />
                <Vector
                  label="缩放"
                  value={object.scale}
                  min={0.001}
                  max={1000}
                  onChange={(scale) => objectPatch(object.id, { scale })}
                />
                <p>位置与尺寸单位为米，旋转单位为度。</p>
              </div>
            </details>
          </>
        ) : (
          <>
            <p>点击画面中的物体，或从上方列表选择，即可调整大小和颜色。</p>
            <label className="scene-color">
              环境背景
              <input
                aria-label="环境背景"
                type="color"
                value={content.background}
                onChange={(e) =>
                  update({ ...content, background: e.target.value })
                }
              />
            </label>
            <Num
              label="环境光"
              value={content.ambient}
              min={0}
              max={10}
              onChange={(ambient) => update({ ...content, ambient })}
            />
            <LightingSection
              lighting={content.lighting}
              onChange={(lighting) => update({ ...content, lighting })}
            />
          </>
        )}
      </section>
    </div>
  );
}

/**
 * 主光。**预设在最前,旋钮收在下面。**
 *
 * 绝大多数时候用户要的是"我在拍产品/拍人/拍空间",按用途挑一档就走;真要抠角度的人才展开
 * 那四个数。把旋钮摊在第一屏,等于要求每个人先懂布光才能用这一页。
 *
 * 手动改过任何一个数就落到 `custom` —— 那时预设那句写好的提示词已经不描述当前的光了,
 * 交给模型的话会由 `lightingPrompt` 按当时的数现生成一句。
 */
/**
 * 物体的走位。
 *
 * **和相机的运镜是同一条时间轴上的同一件事** —— 只是记的字段不同(物体记位置/旋转/缩放,
 * 相机记位置/注视点/视角)。见 docs/design/scene-time-and-cameras.md。
 *
 * 「记录此刻」而不是"打开动画模式":用户已经把物体摆到想要的地方了,剩下的只是说一句
 * "它在第几秒是这样"。第一次记会**连同当前的静止姿态一起记成 0 秒那一档** ——
 * 否则从静止位置到你记的这一档之间没有任何东西描述它,播放时会突然跳过去。
 */
function ObjectTrackSection({
  object,
  time,
  onPatch,
}: {
  object: SceneObject;
  time: number;
  onPatch: (patch: Partial<SceneObject>) => void;
}) {
  const track = object.track;
  const index = track.findIndex((f) => Math.abs(f.time - time) < 0.001);
  const record = () => {
    const now = {
      time: Math.max(0, time),
      position: object.position,
      rotation: object.rotation,
      scale: object.scale,
    };
    const base = track.length
      ? track
      : [{ time: 0, position: object.position, rotation: object.rotation, scale: object.scale }];
    const next = [...base.filter((f) => Math.abs(f.time - now.time) > 0.001), now].sort(
      (a, b) => a.time - b.time,
    );
    if (next.length > 100) return;
    onPatch({ track: next });
  };
  return (
    <details className="scene-details" open={!!track.length}>
      <summary>走位（随时间移动）</summary>
      <div>
        <div className="scene-shape">
          <Button variant="secondary" onClick={record}>
            <Clock size={15} />
            记录此刻
          </Button>
          {!!track.length && (
            <Button variant="outline" onClick={() => onPatch({ track: [] })}>
              清除走位
            </Button>
          )}
        </div>
        {track.length ? (
          <>
            <p>
              {track.length} 个时刻：
              {track.map((f) => `${f.time.toFixed(1)}s`).join("、")}
            </p>
            {index >= 0 && (
              <Button
                variant="outline"
                onClick={() => onPatch({ track: track.filter((_, i) => i !== index) })}
              >
                移除 {track[index].time.toFixed(1)}s 这一档
              </Button>
            )}
          </>
        ) : (
          <p>把物体摆到位，再点「记录此刻」。在时间条上换一个时刻、挪一下，它就会在两点之间走过去。</p>
        )}
      </div>
    </details>
  );
}

/** 少数几类的参数在它自己的语汇里有更准的名字。人物那三个数叫「宽度/高度/深度」是对的但
 *  没用 —— 调的人想的是身高和肩宽,名字贴着它实际是什么,省掉一次心里的换算。 */
/** 「不在组里」在 Select 里要有一个值 —— 空串会被 Radix 当成"没选" 。 */
const TOP_LEVEL = "__top__";

const PARAMETER_LABELS: Partial<
  Record<SceneObject["kind"], Partial<Record<keyof SceneObject["parameters"], string>>>
> = {
  figure: { width: "肩宽", height: "身高", depth: "厚度" },
  table: { width: "台面宽", height: "桌高", depth: "台面深" },
};

function LightingSection({
  lighting,
  onChange,
}: {
  lighting: SceneLighting;
  onChange: (lighting: SceneLighting) => void;
}) {
  const tune = (patch: Partial<SceneLighting>) =>
    onChange({ ...lighting, ...patch, preset: CUSTOM_PRESET });
  const current = presetById(lighting.preset);
  return (
    <details className="scene-details" open>
      <summary>主光</summary>
      <div>
        <label className="scene-number">
          <span>打光方式</span>
          <Select
            value={lighting.preset}
            onValueChange={(id) => {
              const picked = presetById(id);
              if (picked) onChange({ preset: picked.id, ...picked.values });
            }}
          >
            <SelectTrigger aria-label="打光方式">
              <SelectValue placeholder="自定义" />
            </SelectTrigger>
            <SelectContent>
              {presetGroups().map(([group, presets]) => (
                <SelectGroup key={group}>
                  <SelectLabel>{group}</SelectLabel>
                  {presets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.id}>
                      {preset.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </label>
        <p>{current ? current.hint : "已手动调整。选一档预设可以回到成套的参数。"}</p>
        <div className="scene-shape">
          <Num
            label="方位角"
            caption="方位角°"
            value={lighting.azimuth}
            min={0}
            max={359}
            step={5}
            onChange={(azimuth) => tune({ azimuth })}
          />
          <Num
            label="高度角"
            caption="高度角°"
            value={lighting.elevation}
            min={0}
            max={90}
            step={5}
            onChange={(elevation) => tune({ elevation })}
          />
          <Num
            label="强度"
            caption="强度"
            value={lighting.intensity}
            min={0}
            max={20}
            step={0.1}
            onChange={(intensity) => tune({ intensity })}
          />
          <Num
            label="色温"
            caption="色温 K"
            value={lighting.temperature}
            min={1500}
            max={12000}
            step={100}
            onChange={(temperature) => tune({ temperature: Math.round(temperature) })}
          />
        </div>
        <Num
          label="影子软硬"
          caption="影子软硬（0 硬 · 1 柔）"
          value={lighting.softness}
          min={0}
          max={1}
          step={0.05}
          onChange={(softness) => tune({ softness })}
        />
        <p>方位角 0 是正面来光，90 在右侧，180 是逆光；高度角 0 贴地、90 是顶光。</p>
      </div>
    </details>
  );
}
