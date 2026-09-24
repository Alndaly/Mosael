import React from "react";
import { SceneSubsection } from "./SceneSubsection";
import { Copy, Eye, EyeOff, Group, Trash2 } from "lucide-react";
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
import { duplicateObject, groupPath, groupTargets, makeObject, moveToGroup } from "./sceneGraph";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
export function SceneInspector({
  content,
  object,
  objectPatch,
  update,
  onRemove,
  setSelected,
}: {
  content: SceneContent;
  object: SceneObject | undefined;
  objectPatch: (id: string, patch: Partial<SceneObject>) => void;
  update: (c: SceneContent) => void;
  onRemove: (ids: string[]) => void;
  setSelected: (id: string | null) => void;
}) {
  const t = useI18n();
  //: 外壳、标题、左右内距和竖向节奏全归 ScenePanel(见 .scene-panel-body) —— 这里只出内容,
  //: 连一层 div 都不包。此前这里还套着 `.scene-inspector > section`,而那一层唯一的作用就是
  //: 再写一套自己的 padding 和 gap:右栏于是有三处各自定义的左边距,三节内容的左边缘对不齐。
  return (
    <>
      {object ? (
          <>
            <Input
              aria-label={t("sceneObjectName")}
              value={object.name}
              maxLength={160}
              onChange={(e) => objectPatch(object.id, { name: e.target.value })}
            />
            {/* **「移到…」是「组」此前缺的那一半。** 数据模型一直支持 parent_id,但界面上没有
                任何入口能把已有的物体放进已有的组 —— 于是菜单里那个空组建完就废。
                选择器而不是拖拽:长列表 + 触控板上拖拽很难瞄准,而且选择器天生可键盘操作。 */}
            {!!groupTargets(content, object.id).length && (
              <label className="scene-number">
                <span>{t("sceneObjectGroup")}</span>
                <Select
                  value={object.parent_id ?? TOP_LEVEL}
                  onValueChange={(value) =>
                    update(moveToGroup(content, object.id, value === TOP_LEVEL ? null : value))
                  }
                >
                  <SelectTrigger aria-label={t("sceneObjectGroup")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={TOP_LEVEL}>{t("sceneObjectNoGroup")}</SelectItem>
                    {/* 带上上级:「添加 → 组」建出来的都叫「组」,嵌套之后一列全是「组」,
                        选哪个全靠猜。 */}
                    {groupTargets(content, object.id).map((group) => (
                      <SelectItem key={group.id} value={group.id}>
                        {groupPath(content, group.id)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            )}
            <div className="scene-actions">
              <Tool
                label={t("sceneObjectDuplicate")}
                onClick={() => update(duplicateObject(content, object.id, t))}
              >
                <Copy size={15} />
              </Tool>
              <Tool
                label={t("sceneObjectGroupUp")}
                onClick={() => {
                  const group = makeObject("group", {
                    name: t("sceneGroupOf").replace("{name}", object.name),
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
                label={t("sceneObjectDelete")}
                onClick={() => onRemove([object.id])}
              >
                <Trash2 size={15} />
              </Tool>
              {/* 一行里四个动作,四个都是图标钮。此前最后这个是文字钮,于是同一行里
                  三个方块加一段文字,行高和重心都对不齐 —— 而它和另外三个是同一类操作。 */}
              <Tool
                label={object.hidden ? t("sceneObjectShow") : t("sceneObjectHide")}
                active={object.hidden}
                onClick={() =>
                  objectPatch(object.id, { hidden: !object.hidden })
                }
              >
                {object.hidden ? <EyeOff size={15} /> : <Eye size={15} />}
              </Tool>
            </div>
            {/* 相机没有形状,也没有颜色和材质 —— 它有的是视角。此前它跟着几何体一起显示
                「宽度/高度/深度/粗糙度/金属度」,那些字段对它一个都不成立。 */}
            {object.kind === "camera" && (
              <Num
                label={t("sceneObjectFov")}
                caption={t("sceneObjectFovCaption")}
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
                        t(PARAMETER_LABELS[object.kind]?.[k] ?? DEFAULT_PARAMETER_LABELS[k])
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
                  {t("sceneObjectColor")}
                  <input
                    aria-label={t("sceneObjectColorLabel")}
                    type="color"
                    value={object.color}
                    onChange={(e) =>
                      objectPatch(object.id, { color: e.target.value })
                    }
                  />
                </label>
                {object.kind === "light" ? (
                  <Num
                    label={t("sceneLightIntensity")}
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
                      label={t("sceneObjectRoughness")}
                      value={object.roughness}
                      min={0}
                      max={1}
                      onChange={(roughness) =>
                        objectPatch(object.id, { roughness })
                      }
                    />
                    <Num
                      label={t("sceneObjectMetalness")}
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
            <SceneSubsection expanded title={t("sceneObjectTransform")}>
                {" "}
                <Vector
                  label={t("sceneObjectPosition")}
                  value={object.position}
                  onChange={(position) => objectPatch(object.id, { position })}
                />
                <Vector
                  label={t("sceneObjectRotation")}
                  value={object.rotation}
                  onChange={(rotation) => objectPatch(object.id, { rotation })}
                />
                <Vector
                  label={t("sceneObjectScale")}
                  value={object.scale}
                  min={0.001}
                  max={1000}
                  onChange={(scale) => objectPatch(object.id, { scale })}
                />
                <p>{t("sceneObjectUnits")}</p>
              </SceneSubsection>
          </>
        ) : (
          <>
            <p>{t("sceneInspectorEmpty")}</p>
            <label className="scene-color">
              {t("sceneBackground")}
              <input
                aria-label={t("sceneBackground")}
                type="color"
                value={content.background}
                onChange={(e) =>
                  update({ ...content, background: e.target.value })
                }
              />
            </label>
            <Num
              label={t("sceneAmbient")}
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
    </>
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
/** 少数几类的参数在它自己的语汇里有更准的名字。人物那三个数叫「宽度/高度/深度」是对的但
 *  没用 —— 调的人想的是身高和肩宽,名字贴着它实际是什么,省掉一次心里的换算。 */
/** 「不在组里」在 Select 里要有一个值 —— 空串会被 Radix 当成"没选" 。 */
const TOP_LEVEL = "__top__";

const PARAMETER_LABELS: Partial<
  Record<SceneObject["kind"], Partial<Record<keyof SceneObject["parameters"], MessageKey>>>
> = {
  figure: { width: "sceneParamShoulderWidth", height: "sceneParamBodyHeight", depth: "sceneParamThickness" },
  table: { width: "sceneParamTopWidth", height: "sceneParamTableHeight", depth: "sceneParamTopDepth" },
};

const DEFAULT_PARAMETER_LABELS: Record<keyof SceneObject["parameters"], MessageKey> = {
  width: "sceneParamWidth",
  height: "sceneParamHeight",
  depth: "sceneParamDepth",
  radius: "sceneParamRadius",
  steps: "sceneParamSteps",
  door_width: "sceneParamDoorWidth",
  door_height: "sceneParamDoorHeight",
};

function LightingSection({
  lighting,
  onChange,
}: {
  lighting: SceneLighting;
  onChange: (lighting: SceneLighting) => void;
}) {
  const t = useI18n();
  const tune = (patch: Partial<SceneLighting>) =>
    onChange({ ...lighting, ...patch, preset: CUSTOM_PRESET });
  const current = presetById(lighting.preset);
  return (
    <SceneSubsection expanded title={t("sceneKeyLight")}
        defaultOpen>
        <label className="scene-number">
          <span>{t("sceneLightingPreset")}</span>
          <Select
            value={lighting.preset}
            onValueChange={(id) => {
              const picked = presetById(id);
              if (picked) onChange({ preset: picked.id, ...picked.values });
            }}
          >
            <SelectTrigger aria-label={t("sceneLightingPreset")}>
              <SelectValue placeholder={t("sceneLightingCustom")} />
            </SelectTrigger>
            <SelectContent>
              {presetGroups().map(([group, presets]) => (
                <SelectGroup key={group}>
                  <SelectLabel>{t(group)}</SelectLabel>
                  {presets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.id}>
                      {t(preset.label)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </label>
        <p>{current ? t(current.hint) : t("sceneLightingCustomHint")}</p>
        <div className="scene-shape">
          <Num
            label={t("sceneLightAzimuth")}
            caption={t("sceneLightAzimuthCaption")}
            value={lighting.azimuth}
            min={0}
            max={359}
            step={5}
            onChange={(azimuth) => tune({ azimuth })}
          />
          <Num
            label={t("sceneLightElevation")}
            caption={t("sceneLightElevationCaption")}
            value={lighting.elevation}
            min={0}
            max={90}
            step={5}
            onChange={(elevation) => tune({ elevation })}
          />
          <Num
            label={t("sceneLightStrength")}
            caption={t("sceneLightStrength")}
            value={lighting.intensity}
            min={0}
            max={20}
            step={0.1}
            onChange={(intensity) => tune({ intensity })}
          />
          <Num
            label={t("sceneLightTemperature")}
            caption={t("sceneLightTemperatureCaption")}
            value={lighting.temperature}
            min={1500}
            max={12000}
            step={100}
            onChange={(temperature) => tune({ temperature: Math.round(temperature) })}
          />
        </div>
        <Num
          label={t("sceneLightSoftness")}
          caption={t("sceneLightSoftnessCaption")}
          value={lighting.softness}
          min={0}
          max={1}
          step={0.05}
          onChange={(softness) => tune({ softness })}
        />
        <p>{t("sceneLightAnglesHint")}</p>
    </SceneSubsection>
  );
}
