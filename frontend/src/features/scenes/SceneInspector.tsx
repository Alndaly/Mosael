import React from "react";
import { Copy, Group, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import type { SceneContent, SceneObject } from "@/api/domains/scenes";
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
          </>
        )}
      </section>
    </aside>
  );
}
