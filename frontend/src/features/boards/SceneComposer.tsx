import React from "react";
import { Box, Loader2 } from "lucide-react";

import type { BoardItem, BoardProducerInfo, BoardRunForms } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { BAR_PICKER, BoardComposerShell } from "@/features/boards/BoardComposerShell";
import { SceneOverview } from "@/features/boards/SceneOverview";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { NodeConfigForm, useNodeFieldOptions, type ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { cn } from "@/lib/utils";

type Form = BoardRunForms["scene_render"];
type Config = Form["config"];

/** 底栏上的两枚芯片:镜头、渲什么。其余(归档进哪个项目)进「参数」。 */
const SHOT = "shot_id";
const RENDER = "render";

/**
 * 3D 场景格的面板:**渲染是场景格自己会做的事**。此前一格场景格旁边还要放一格「渲染白模参考」工具格,
 * 在工具格上再挑一遍场景 —— 同一件事的两半;现在选中场景格,挑镜头、挑渲什么,点发送,首尾帧 / 运镜视频
 * 新建在右边(和一格的能力同一个执行器、同一种任务,见后端 producers 的 scene_render)。
 *
 * **和画板上别的面板同一个壳**(BoardComposerShell):
 *
 *  · 正文是这一格引用的场景:一张小缩略图(导出过的话)、场景名、「编辑场景」—— 构图、加镜头在场景页做;
 *  · 底栏是两枚芯片,和能力面板的芯片同一个样子(OptionPicker + BAR_PICKER,宽度上限挂在外层包装上):
 *    「镜头 ▾」写的是值(镜头名),没选时写字段名;场景一个镜头都没有时是灰的,悬停说为什么。
 *    「渲染内容 ▾」三选一。
 *  · 圆形发送键:还差什么(好几个镜头却没挑、场景没有镜头)就是灰的,悬停说差哪样 —— 和能力面板同一句。
 *
 * 字段的名字、说明、选项来源、「只有一个镜头就用它」都读后端发的那一份声明(工作流节点 `scene_render` 的字段,
 * 少了场景):镜头清单按这一格的场景查(`boundValues`),不在前端另写一份。
 */
export function SceneComposer({
  item,
  producer,
  workspaceId,
  busy,
  onFormChange,
  onRun,
}: {
  /** 面板看到的那一格(表单里不带产出者)。 */
  item: BoardItem;
  /** 渲白模的声明(后端 GET /api/boards/producers 的 scene_render)。undefined = 清单还在路上。 */
  producer: BoardProducerInfo | undefined;
  workspaceId: string;
  busy: boolean;
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
  onRun: (form: Form) => Promise<unknown>;
}) {
  const t = useI18n();
  const specs = React.useMemo(() => (producer?.config ?? {}) as Record<string, ConfigSpec>, [producer]);
  const config = React.useMemo(() => (item.form?.config ?? {}) as Config & Record<string, unknown>, [item.form?.config]);
  //: 镜头跟着场景走:场景就是这一格引用的那一个。
  const boundValues = React.useMemo(() => ({ scene_id: item.scene_id ?? "" }), [item.scene_id]);
  const fieldOptions = useNodeFieldOptions({ specs, config, workspaceId, nodeType: producer?.type ?? "", boundValues });
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const setConfig = (key: string, value: unknown) => onFormChange({ ...item.form, config: { ...config, [key]: value } });
  const label = (key: string) => String(specs[key]?.label || key);

  const shotSpec = specs[SHOT];
  const shots = shotSpec ? (fieldOptions.dynamicOptions(SHOT, shotSpec) ?? []) : [];
  const shotsLoading = shots.length === 0 && fieldOptions.whyEmpty(SHOT).kind === "pending";
  const savedShot = String(config.shot_id ?? "");
  //: 存着的镜头这个场景里没有(按文字重搭换了场景,旧场景的镜头 id 还在表单里)就当没挑 —— 否则挑选器拿着一个
  //: 对不上任何选项的值,既不显示镜头名也不显示「镜头」,只剩一个箭头(用户截图)。清单还在查的时候先不判。
  const chosenShot = shotsLoading || shots.some((one) => one.value === savedShot) ? savedShot : "";
  //: 留空 = 唯一的那一个镜头(sole_option_default):显示成当前值,不写进表单 —— 运行时同一条规矩。
  const shot = !chosenShot && shotSpec?.sole_option_default && shots.length === 1 ? shots[0].value : chosenShot;
  const noShots = Boolean(shotSpec) && shots.length === 0 && !shotsLoading;

  const renderSpec = specs[RENDER];
  const renders = (renderSpec?.options ?? []).map((one) => ({ value: one, label: renderSpec?.option_labels?.[one] ?? one }));
  const render = String(config.render ?? renderSpec?.default ?? "");

  //: 还差哪样:好几个镜头却没挑、一个镜头都没有(清单还在查的时候不算缺)。
  const missing = shotSpec && !shot && !shotsLoading ? [label(SHOT)] : [];
  //: 镜头清单还在查:先别发(发出去的可能是「好几个镜头却没挑」)。
  const blocked = !producer || shotsLoading || missing.length > 0;
  const send = () => {
    if (blocked || working) return;
    //: 只发渲白模自己的那几项:这一格的 config 和「按文字搭」共用一份(切换填法时表单不清),把那边的字段一起发过去
    //: 会被服务端拒(渲白模的表单不收不认识的键)。对不上的旧镜头 id 也不发(服务端会说找不到这个镜头)。
    const own = Object.fromEntries(Object.entries(config).filter(([key]) => key in specs && (key !== SHOT || chosenShot)));
    run(() => onRun({ config: own }));
  };

  const rest = Object.entries(specs).filter(([key]) => key !== SHOT && key !== RENDER);

  const chip = (key: string, value: string, options: { value: string; label: string }[], why: string) => (
    <span
      key={key}
      data-field-key={key}
      //: 宽度上限挂在**这一层**,芯片撑满它 —— 上限写在芯片上的话,百分比相对的是这层按内容定宽的包装,
      //: 一来一回把字压成 0(见 AbilityComposer 的同一处)。
      className="flex min-w-0 max-w-[min(15rem,45%)] shrink"
      title={why ? `${label(key)} · ${why}` : label(key)}
    >
      <OptionPicker
        size="sm"
        ariaLabel={label(key)}
        value={value}
        onChange={(next) => setConfig(key, next)}
        options={options}
        disabled={options.length === 0}
        placeholder={label(key)}
        className={cn(BAR_PICKER, "max-w-full", value && "text-foreground")}
        contentClassName="max-w-[min(360px,calc(100vw-16px))]"
      />
    </span>
  );

  return (
    <BoardComposerShell
      nodeId={item.id}
      name="scene"
      bar={
        producer ? (
          <>
            {shotSpec ? chip(SHOT, shot, shots, noShots ? t("boardSceneNoShots") : shotsLoading ? t("wfOptionsLoading") : "") : null}
            {renderSpec ? chip(RENDER, render, renders, "") : null}
          </>
        ) : null
      }
      settings={
        producer && rest.length > 0
          ? {
              content: (
                <NodeConfigForm
                  compact
                  fields={rest}
                  config={config}
                  workspaceId={workspaceId}
                  variables={[]}
                  fieldOptions={fieldOptions}
                  onSetConfig={setConfig}
                  onTypeConfig={setConfig}
                />
              ),
            }
          : null
      }
      send={
        producer
          ? {
              label: t(item.run?.status === "succeeded" ? "boardSceneRenderAgain" : "boardSceneRender"),
              hint: noShots
                ? t("boardSceneNoShots")
                : missing.length > 0
                  ? t("boardToolMissing").replace("{fields}", missing.join(t("listSeparator")))
                  : t("boardToolOutputsHint"),
              onSend: send,
              disabled: blocked,
              working,
            }
          : null
      }
    >
      <div data-scene-composer-scene="" className="flex min-w-0 items-center gap-2.5 px-1 py-1">
        <div className="grid h-10 w-16 shrink-0 place-items-center overflow-hidden rounded-md border border-border bg-secondary/40 text-muted-foreground">
          {item.scene_id ? (
            <SceneOverview key={item.scene_id} workspaceId={workspaceId} sceneId={item.scene_id} fallback={<Box size={16} strokeWidth={1.4} />} />
          ) : (
            <Box size={16} strokeWidth={1.4} />
          )}
        </div>
        {/* 「编辑场景」在格子上方的操作条上(换到「按文字搭」也在),这里不再放一份。 */}
        <span data-scene-name="" className="min-w-0 flex-1 truncate text-ui-sm text-foreground" title={item.text}>
          {item.text || t("boardKindScene")}
        </span>
      </div>
      {producer === undefined ? (
        <div role="status" className="flex items-center gap-2 px-1 text-ui-xs text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> {t("boardKindScene")}
        </div>
      ) : noShots ? (
        <p role="alert" className="m-0 px-1 text-ui-xs leading-relaxed text-muted-foreground">
          {t("boardSceneNoShots")}
        </p>
      ) : null}
    </BoardComposerShell>
  );
}
