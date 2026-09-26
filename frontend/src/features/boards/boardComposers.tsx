import type React from "react";

import {
  isNodeProducer,
  type BoardAbilitySetting,
  type BoardItem,
  type BoardProducer,
  type BoardProducerInfo,
  type NodeProducer,
  type BoardRunRequest,
  type BuiltinProducer,
  type GenerationOption,
} from "@/api/client";
import { AbilityComposer } from "@/features/boards/AbilityComposer";
import { AudioComposer } from "@/features/boards/AudioComposer";
import { NodeComposer } from "@/features/boards/NodeComposer";
import { NoteComposer } from "@/features/boards/NoteComposer";
import { SceneComposer } from "@/features/boards/SceneComposer";
import { TrimComposer } from "@/features/boards/TrimComposer";
import { itemFormResetKey, itemIsRunning, producerOf } from "@/features/boards/boardItemState";
import type { BoardDocumentState } from "@/features/boards/boardDocumentSources";
import type { MediaKind } from "@/features/boards/boardNodes";
import type { Upstream } from "@/features/boards/boardUpstream";

/** 画布交给面板的东西:挂在哪一格、上游给了什么、怎么存表单、怎么跑。 */
export interface ComposerHost {
  /** 面板看到的那一格(表单里不带产出者,见 boardItemState.composerView)。 */
  item: BoardItem;
  /** 那一格此刻在画布上的位置(拖过的话和 item 上记的不同)。 */
  position: { x: number; y: number };
  workspaceId: string;
  feeding: Upstream;
  documents: Map<string, BoardDocumentState>;
  models: GenerationOption[];
  /** 这张便签正在写(写字是同步的几秒,期间按钮转圈)。 */
  writing: boolean;
  setWriting: (itemId: string | null) => void;
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
  onPickAsset: (kind: MediaKind, place: (assetId: string) => void) => void;
  /** 跑这一格的产出者(见 BoardsView.run → runOnBoard)。 */
  run: (request: BoardRunRequest) => Promise<unknown>;
  /** 这个人能用的产出者清单(后端 GET /api/boards/producers)。还没到是 undefined。 */
  producers?: BoardProducerInfo[];
}

/**
 * 内置产出者各自的面板,按产出者挂(见 boardItemState.producerOf)。**一张表,不是四段条件渲染** ——
 * 此前 BoardCanvas 里按「这是哪种面板」各写一段,面板自己再按种类猜;现在一格挂哪块由它表单上的
 * 产出者说了算,节点产出者(能力、生成器)一律是 AbilityComposer。
 *
 * 面板本身不认识画板的接口:它们交出自己那几个字段,这里拼成一次 runOnBoard 的请求。
 */
export const BUILTIN_COMPOSERS: Record<BuiltinProducer, (host: ComposerHost) => React.ReactNode> = {
  //: 便签:写文案。**和图片/视频不是同一张表** —— 写字没有比例、时长、参考图这些东西,
  //: 硬塞进同一个组件里会长出一堆「文本的时候不显示」的分支。
  write: ({ item, position, workspaceId, feeding, writing, setWriting, onFormChange, run }) => (
    <NoteComposer
      key={itemFormResetKey(item)}
      item={item}
      busy={writing}
      workspaceId={workspaceId}
      //: 上游连过来的素材,**不只是图**:视频抽帧给它看,音频有转写就当材料 ——
      //: 一段片子连到便签,意思就是「照着这段写」。
      upstreamAssets={feeding.assets.map((one) => one.assetId)}
      //: 上游便签的字当**材料**,不是提示词 —— 「接着这段往下写」里,那段是素材,
      //: 用户在框里打的才是指令。
      upstreamTexts={feeding.texts.map((one) => one.text)}
      onFormChange={onFormChange}
      onWrite={({ prompt, providerProfileId, model, assets, context }) => {
        setWriting(item.id);
        return run({
          producer: "write",
          item_id: item.id,
          kind: item.kind,
          ...position,
          form: { prompt, provider_profile_id: providerProfileId, model, source_assets: assets, context },
        }).finally(() => setWriting(null));
      }}
    />
  ),

  //: 音频:念一段文字。**不是「生成」那条路** —— 出图出片选生成模型,念字选的是音色。
  speak: ({ item, position, workspaceId, feeding, onFormChange, run }) => (
    <AudioComposer
      key={itemFormResetKey(item)}
      item={item}
      busy={itemIsRunning(item)}
      workspaceId={workspaceId}
      //: 上游便签的字**就是要念的内容** —— 让用户再抄一遍,那条线就白连了。
      upstreamText={feeding.texts.map((one) => one.text).join("\n\n")}
      onFormChange={onFormChange}
      onSpeak={({ text, voiceId, engine, engineVoice }) =>
        void run({
          producer: "speak",
          item_id: item.id,
          kind: item.kind,
          ...position,
          form: { text, voice_id: voiceId, engine, engine_voice: engineVoice },
        })
      }
    />
  ),

  //: 截出来的那一格还没有产出(截挂了、还在截):照表单上记的那份、那段就地再截。不吃上游。
  trim: ({ item, position, workspaceId, run }) => {
    const source = item.form?.trim;
    const kind = item.kind;
    if (!source || (kind !== "video" && kind !== "audio")) return null;
    return (
      <TrimComposer
        key={itemFormResetKey(item)}
        item={{ ...item, kind }}
        assetId={source.asset_id}
        initial={source}
        workspaceId={workspaceId}
        busy={itemIsRunning(item)}
        onTrim={({ start, end, mute }) =>
          void run({
            producer: "trim",
            item_id: item.id,
            kind,
            ...position,
            form: { asset_id: source.asset_id, start, end, mute },
          })
        }
      />
    );
  },

  //: 3D 场景格:从它的一个镜头渲白模参考。渲染是场景格自己会做的事(此前是旁边另放一格工具格);
  //: 字段照后端的声明长(镜头、渲什么),产出新建在右边。不吃上游 —— 场景就是这一格。
  scene_render: ({ item, position, workspaceId, producers, onFormChange, run }) => (
    <SceneComposer
      key={item.id}
      item={item}
      //: 声明从清单里认:挂得在这种格子上、表单就是运行那一份(`runs_from_draft`)的那一个 —— 字段照它长。
      producer={producers?.find((one) => one.id === "scene_render" && one.runs_from_draft && one.hosts.includes(item.kind))}
      workspaceId={workspaceId}
      busy={itemIsRunning(item)}
      onFormChange={onFormChange}
      onRun={(form) => run({ producer: "scene_render", item_id: item.id, kind: item.kind, ...position, form })}
    />
  ),

  //: 还没有产出的图片/视频槽:提示词面板 —— 节点本身就是生成单元。
  generate: ({ item, position, workspaceId, feeding, documents, models, onFormChange, onPickAsset, run }) => (
    <NodeComposer
      key={itemFormResetKey(item)}
      item={item}
      models={models}
      busy={itemIsRunning(item)}
      onPickAsset={onPickAsset}
      workspaceId={workspaceId}
      upstream={feeding.assets}
      upstreamTexts={feeding.texts.filter((one) => !documents.has(one.itemId))}
      upstreamDocuments={feeding.references}
      onFormChange={onFormChange}
      onSubmit={({ prompt, provider, providerProfileId, model, parameters, sourceAssets, form }) =>
        void run({
          producer: "generate",
          item_id: item.id,
          kind: item.kind,
          ...position,
          form: {
            prompt,
            provider,
            provider_profile_id: providerProfileId,
            model,
            parameters,
            source_assets: sourceAssets,
            item_form: form,
          },
        })
      }
    />
  ),
};

/** 这个人清单里的那一项:清单没到是 undefined,查不到(插件卸了、他没有连接)是 null。 */
function findTool(producers: BoardProducerInfo[] | undefined, id: string): BoardProducerInfo | null | undefined {
  return producers === undefined ? undefined : (producers.find((one) => one.id === id) ?? null);
}

/**
 * 一格该挂的面板(它**自己的**产出者)。内置的查上面那张表;`node:*`(空格子上的生成器)一律是 AbilityComposer
 * 的生成器那一种 —— 表单照节点声明长出来,不为哪个工具单写。工具在不在这个人的清单里由面板自己说。
 */
export function renderComposer(producer: BoardProducer, host: ComposerHost): React.ReactNode {
  if (!isNodeProducer(producer)) return BUILTIN_COMPOSERS[producer](host);
  const { item, position, workspaceId, feeding, producers, onFormChange, run } = host;
  return (
    <AbilityComposer
      key={`${item.id}:${producer}`}
      item={item}
      tool={findTool(producers, producer)}
      setting={{ config: item.form?.config, bindings: item.form?.bindings }}
      sources={feeding.sources}
      workspaceId={workspaceId}
      busy={itemIsRunning(item)}
      onFormChange={(setting) => onFormChange({ ...item.form, ...setting })}
      onRun={(form) => run({ producer, item_id: item.id, kind: item.kind, ...position, form })}
    />
  );
}

/**
 * 一格的一项**能力**的面板(操作条上点开的那一项)。宿主就是这一格:它的内容是工具的那个输入(`host_fields`),
 * 设置存在它的 `form.abilities[能力]` 上(`onSave`,见 boardItemState.withAbility),产出新建在它右边。
 */
export function renderAbility(
  ability: BoardProducer,
  host: Omit<ComposerHost, "onFormChange"> & { item: BoardItem; onSave: (setting: BoardAbilitySetting) => void },
): React.ReactNode {
  const { item, position, workspaceId, feeding, producers, onSave, run } = host;
  const tool = findTool(producers, ability);
  return (
    <AbilityComposer
      key={`${item.id}:${ability}`}
      item={item}
      tool={tool}
      hostField={tool?.host_fields?.[item.kind] ?? null}
      setting={item.form?.abilities?.[ability] ?? {}}
      sources={feeding.sources}
      workspaceId={workspaceId}
      busy={itemIsRunning(item)}
      onFormChange={onSave}
      onRun={(form) => run({ producer: ability as NodeProducer, item_id: item.id, kind: item.kind, ...position, form })}
    />
  );
}

/**
 * 一格空槽能在哪几个产出者之间切换:能填空槽(`fills_empty_slot`)、又挂得在这种格子上的那几个 —— 内置的
 * (配音 / 生成)和插件的生成器(按参数出图出片的 ComfyUI 工作流、Manim 动画……)。只有一个就不用切。
 * 音频槽在「配音」和「生成(音乐、音效)」之间切,就是这一条 —— 生成目录一认音频,后端 generate 的 hosts 里
 * 就有 audio,这里不用改。
 */
export function slotProducers(item: BoardItem, producers: BoardProducerInfo[] | undefined): BoardProducerInfo[] {
  if (!producers || item.asset_id) return [];
  const fitting = producers.filter((one) => one.fills_empty_slot && one.hosts.includes(item.kind));
  return fitting.length > 1 ? fitting : [];
}

/**
 * 这个产出者的面板**选中就挂**,还是**等人点了才挂**。写字是便签的一个帮手,不是便签本身:便签首先是
 * 自己写的字,选中它多半是要挪一挪、改个颜色 —— 此前一选中就弹出写作面板,挪一张便签也得先把它关掉。
 * 写作面板由操作条上的「让 AI 写」打开(BoardCanvas 的 panel)。别的产出者的格子(空的图片 / 视频槽、
 * 空格子上的生成器)选中它就是要跑它,面板照旧直接挂。一张表,不按产出者名字逐个比。
 */
const COMPOSER_ON_DEMAND: Record<BuiltinProducer, boolean> = {
  write: true,
  generate: false,
  speak: false,
  trim: false,
  scene_render: false,
};

export function composerOnDemand(producer: BoardProducer): boolean {
  return !isNodeProducer(producer) && COMPOSER_ON_DEMAND[producer];
}

/** 这一格能不能打开按需的面板(「让 AI 写」)。能力交回的结构化数据(JSON 便签)不给 —— 它是一份数据,
 *  不是一段要改写的文案。 */
export function canAskWriter(item: BoardItem): boolean {
  const producer = producerOf(item);
  return Boolean(producer && composerOnDemand(producer) && item.text_format !== "json");
}
