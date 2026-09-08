import React from "react";
import { Copy, Group, Trash2 } from "lucide-react";
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
import { duplicateObject, makeObject, removeObjects } from "./sceneGraph";
export function SceneInspector({
  content,
  object,
  objectPatch,
  update,
  setSelected,
}: {
  content: SceneContent;
  object: SceneObject | undefined;
  objectPatch: (id: string, patch: Partial<SceneObject>) => void;
  update: (c: SceneContent) => void;
  setSelected: (id: string | null) => void;
}) {
  return (
    <aside className="scene-inspector">
      <section>
        <h2>{object ? "调整物体" : "场景外观"}</h2>
        {object ? (
          <>
            <Input
              aria-label="对象名称"
              value={object.name}
              maxLength={160}
              onChange={(e) => objectPatch(object.id, { name: e.target.value })}
            />
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
            {!["model", "group", "light"].includes(object.kind) && (
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
            {!["group", "model"].includes(object.kind) && (
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
    </aside>
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
