import type React from "react";

import type { BoardItem, BoardProducer, BoardRunRequest, GenerationOption } from "@/api/client";
import { AudioComposer } from "@/features/boards/AudioComposer";
import { NodeComposer } from "@/features/boards/NodeComposer";
import { NoteComposer } from "@/features/boards/NoteComposer";
import { TrimComposer } from "@/features/boards/TrimComposer";
import { itemFormResetKey, itemIsRunning } from "@/features/boards/boardItemState";
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
}

/**
 * 内置产出者各自的面板,按产出者挂(见 boardItemState.producerOf)。**一张表,不是四段条件渲染** ——
 * 此前 BoardCanvas 里按「这是哪种面板」各写一段,面板自己再按种类猜;现在一格挂哪块由它表单上的
 * 产出者说了算,新的产出者(P2 的工具格)只是这张表里多一行。
 *
 * 面板本身不认识画板的接口:它们交出自己那几个字段,这里拼成一次 runOnBoard 的请求。
 */
export const BUILTIN_COMPOSERS: Record<BoardProducer, (host: ComposerHost) => React.ReactNode> = {
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
