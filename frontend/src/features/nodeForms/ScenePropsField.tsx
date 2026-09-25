/**
 * 「可用的 3D 道具」节点上挑模型的那一格。
 *
 * 值的形状很普通(一串逗号分隔的 id),挑的过程不普通:要列出这个工作区里的 3D 模型、能多选。
 * 通用的字段渲染器给不了这个 —— 它的动态选项控件是单选的。所以这里是一个专用控件,由后端的
 * 字段声明点名(`editor: "scene_models"`),而**不是前端按「节点类型 + 字段名」认出来的** ——
 * 后者正是这份节点注册表一直在消灭的那种手抄表。
 *
 * 一个都不勾 = 这个工作区里的全部模型。这和"没有可用道具"是两回事,所以那句话要写出来。
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";

import { listSceneModels } from "@/api/domains/scenes";
import { useI18n } from "@/app/preferences";
import { Checkbox } from "@/components/ui/checkbox";

/** 逗号分隔的 id 串 ⇄ id 集合。空串就是空集(= 全部)。 */
export function parseIds(value: string): string[] {
  return value
    .split(",")
    .map((one) => one.trim())
    .filter(Boolean);
}

export function ScenePropsField({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: string;
  onChange: (next: string) => void;
}) {
  const t = useI18n();
  const models = useQuery({
    queryKey: ["scene-models", workspaceId],
    queryFn: () => listSceneModels(workspaceId),
  });
  const picked = React.useMemo(() => new Set(parseIds(value)), [value]);

  function toggle(id: string, on: boolean) {
    const next = new Set(picked);
    if (on) next.add(id);
    else next.delete(id);
    onChange([...next].join(","));
  }

  if (models.isPending)
    return <small className="text-muted-foreground">{t("modelListLoading")}</small>;
  if (!(models.data ?? []).length)
    return <small className="text-muted-foreground">{t("wfPropsNone")}</small>;

  return (
    <div className="grid gap-1">
      <div className="grid max-h-40 gap-0.5 overflow-y-auto rounded-md border border-border p-1.5">
        {(models.data ?? []).map((model) => (
          <label
            key={model.id}
            className="flex min-w-0 cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-ui-xs hover:bg-secondary"
          >
            <Checkbox
              checked={picked.has(model.id)}
              onCheckedChange={(on) => toggle(model.id, on === true)}
            />
            <span className="min-w-0 truncate">{model.name}</span>
            <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">
              {(model.size / 1024 / 1024).toFixed(1)} MB
            </span>
          </label>
        ))}
      </div>
      {/* 一个都不勾和"没有道具"长得一样,所以要说清楚它的意思。 */}
      <small className="text-muted-foreground">
        {picked.size === 0
          ? t("wfPropsAll")
          : t("wfPropsPicked").replace("{n}", String(picked.size))}
      </small>
    </div>
  );
}
