import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { listAssets, listCapabilityModels, type Asset, type BoardItem } from "@/api/client";
import {
  collect,
  PromptEditor,
  restorePromptDocument,
  type PromptDocument,
} from "@/features/boards/PromptEditor";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { Film, Music, X } from "lucide-react";

import { assetFileUrl, assetPreviewUrl, assetThumbnailUrl } from "@/api/client";
import { useImagePreview } from "@/components/app/image-preview";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";

/**
 * 便签的「写文案」面板。
 *
 * **和图片/视频那张不是同一张表。** 那边的每一项(比例、清晰度、时长、参考图)都由生成描述符
 * 说了算,所以是照着描述符出控件;写字这边没有那些东西 —— 一个模型、一句要求,就这两样。
 * 硬塞进同一个组件的话,里面会长出一堆「文本的时候不显示」的分支,而那正是表单开始骗人的
 * 起点。
 *
 * 模型列的是 **chat 能力 + automation 执行面**下的模型:API Key 走 direct,OAuth 走无工具 gateway。
 */
export function NoteComposer({
  item,
  busy,
  workspaceId,
  upstreamAssets,
  upstreamTexts,
  onWrite,
  onFormChange,
}: {
  item: BoardItem;
  busy: boolean;
  /** `@` 引用素材时去哪个工作区找。 */
  workspaceId: string;
  /** 上游连过来的素材。**让模型看着写** —— 图片和视频给画面,音频给转写(见后端 _look_at)。 */
  upstreamAssets?: string[];
  /** 上游便签给的文字。作为**材料**发过去,和「要求」分开。 */
  upstreamTexts?: string[];
  onWrite: (input: {
    prompt: string;
    providerProfileId: string;
    model: string;
    assets: string[];
    context: string[];
  }) => Promise<unknown>;
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const [prompt, setPrompt] = React.useState(item.form?.prompt ?? "");
  const [mentioned, setMentioned] = React.useState<string[]>(item.form?.mentioned_asset_ids ?? []);
  const [promptDocument, setPromptDocument] = React.useState<PromptDocument | undefined>(
    item.form?.prompt_document as PromptDocument | undefined,
  );
  const [picked, setPicked] = React.useState(
    item.form?.provider_profile_id && item.form?.model
      ? `${item.form.provider_profile_id}:${item.form.model}`
      : "",
  );

  //: `@` 的候选:图片、视频、音频都能引。后端会按类别摊开(图片和视频给画面,音频给转写)——
  //: 只列图片的话,用户明明连得上视频,却 @ 不到它。
  const library = useQuery({ queryKey: ["assets", workspaceId], queryFn: () => listAssets(workspaceId) });
  const candidates = React.useCallback(
    (query: string) => {
      const needle = query.trim().toLowerCase();
      return (library.data ?? [])
        .filter((asset: Asset) => ["image", "video", "audio"].includes(asset.kind))
        .filter(
          (asset: Asset) =>
            !needle || `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle),
        )
        .slice(0, 8);
    },
    [library.data],
  );

  const models = useQuery({
    queryKey: ["capability-models", "chat", "automation"],
    queryFn: () => listCapabilityModels("chat", "automation"),
  });
  const options = models.data ?? [];
  //: 值里带上连接 id:同一个模型名可能挂在两条连接下(自己的和团队的),只存模型名会挑错那条。
  const current = options.find((one) => `${one.provider_profile_id}:${one.model}` === picked) ?? options[0] ?? null;

  // 升级旧节点：旧版只保存纯文本和引用 id。素材库回来后按素材名恢复 chip，并在下一次
  // onFormChange 时把结构化文档补进节点；之后重开不再依赖猜测。
  React.useEffect(() => {
    if (promptDocument || mentioned.length === 0 || !library.data?.length) return;
    const restored = restorePromptDocument(prompt, mentioned, library.data);
    if (collect(restored as { content?: unknown[] }).length > 0) setPromptDocument(restored);
  }, [promptDocument, prompt, mentioned, library.data]);

  const serializedForm = JSON.stringify({
    prompt,
    prompt_document: promptDocument,
    provider_profile_id: current?.provider_profile_id ?? item.form?.provider_profile_id,
    model: current?.model ?? item.form?.model,
    mentioned_asset_ids: mentioned,
  });
  const lastSavedForm = React.useRef(JSON.stringify(item.form ?? {}));
  React.useEffect(() => {
    if (serializedForm === lastSavedForm.current) return;
    lastSavedForm.current = serializedForm;
    onFormChange(JSON.parse(serializedForm) as NonNullable<BoardItem["form"]>);
  }, [serializedForm, onFormChange]);

  //: 这次会发给模型的那几份素材 —— 上游连过来的 + 正文里 @ 到的。**从素材库里查回实体**
  //: 才画得出缩略图(手上只有 id)。
  const referenced = React.useMemo(() => {
    const ids = [...new Set([...(upstreamAssets ?? []), ...mentioned])];
    return ids
      .map((id) => (library.data ?? []).find((asset: Asset) => asset.id === id))
      .filter((asset): asset is Asset => Boolean(asset));
  }, [upstreamAssets, mentioned, library.data]);

  //: 点下去立刻转、落地就停(**失败也要停** —— 否则那个圈会一直转下去)。见 useSubmitting。
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const send = () => {
    const text = prompt.trim();
    if (!text || !current || working) return;
    //: 上游连过来的 + 正文里 @ 到的,一起发。同一张不发两遍。
    const assets = [...new Set([...(upstreamAssets ?? []), ...mentioned])];
    run(() =>
      onWrite({
        prompt: text,
        providerProfileId: current.provider_profile_id,
        model: current.model,
        assets,
        context: upstreamTexts ?? [],
      }),
    );
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={BOARD_NODE_PANEL_OFFSET}>
      <div className="nodrag nopan nowheel w-[420px] rounded-xl border border-border-strong bg-panel p-2 shadow-[var(--shadow-panel)]">
        {/* 连过来的素材摆在最上面。**看得见才知道它在起作用** —— 一条线连过来之后表单上
            什么都不变的话,用户不知道模型到底看没看见那张图。点一下开大图,叉叉解开引用。 */}
        {referenced.length > 0 && (
          <div className="mb-1.5 flex flex-wrap items-center gap-1 border-b border-border px-1 pb-1.5">
            {referenced.map((asset) => (
              <span key={asset.id} className="group/thumb relative shrink-0">
                <button
                  type="button"
                  title={asset.name || asset.original_filename || ""}
                  onClick={() => openImagePreview({
                    src: asset.kind === "image" ? assetPreviewUrl(asset.id) : assetFileUrl(asset.id),
                    title: asset.name || "",
                    ...(asset.kind === "video" ? { video: true } : {}),
                  })}
                  className="block h-8 w-8 cursor-zoom-in overflow-hidden rounded-md border border-border transition-colors hover:border-border-strong"
                >
                  {asset.kind === "image" ? (
                    <img src={assetThumbnailUrl(asset.id)} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <span className="grid h-full w-full place-items-center text-muted-foreground">
                      {asset.kind === "video" ? <Film size={13} /> : <Music size={13} />}
                    </span>
                  )}
                </button>
                {/* 只有正文里 @ 进来的能在这儿摘掉 —— 上游那张是**连线连过来的**,
                    要取消就该去断那条线,在这里给个叉会让两种取消方式打架。 */}
                {mentioned.includes(asset.id) && (
                  <button
                    type="button"
                    aria-label={t("boardRemove")}
                    title={t("boardRemove")}
                    onClick={() => setMentioned((all) => all.filter((one) => one !== asset.id))}
                    className="absolute -right-1 -top-1 grid h-4 w-4 cursor-pointer place-items-center rounded-full border border-border bg-panel text-muted-foreground opacity-0 shadow-sm transition-opacity hover:border-destructive hover:text-destructive group-hover/thumb:opacity-100"
                  >
                    <X size={9} />
                  </button>
                )}
              </span>
            ))}
          </div>
        )}

        <PromptEditor
          value={prompt}
          document={promptDocument}
          onChange={(next, assets, document) => {
            setPrompt(next);
            setMentioned(assets);
            setPromptDocument(document);
          }}
          //: 有字和没字问的**不是同一件事**:一个是「写什么」,一个是「怎么改」。
          //: 用同一句提示语的话,用户会以为它要把整篇重写一遍。
          placeholder={
            (item.text ?? "").trim()
              ? t("boardRewritePlaceholder")
              : t("boardWritePlaceholder")
          }
          candidates={candidates}
          onSubmit={send}
          emptyHint={() => t("boardNoAssetsToMention")}
        />
        <div className="flex items-center gap-1 border-t border-border pt-1.5">
          {options.length === 0 ? (
            // 没有可用模型时说清楚 —— 给一个点了没反应的按钮比什么都不给更糟。
            <span className="px-1 text-ui-2xs text-muted-foreground">{t("boardNoChatModel")}</span>
          ) : (
            <span className="flex min-w-0 shrink items-center gap-0.5 rounded-full px-1 transition-colors hover:bg-secondary">
              <Sparkles size={12} className="shrink-0 text-muted-foreground" />
              <Select value={`${current?.provider_profile_id}:${current?.model}`} onValueChange={setPicked}>
                <SelectTrigger className="h-6 w-auto gap-0 border-0 bg-transparent px-1 text-ui-2xs text-muted-foreground shadow-none focus:ring-0 data-[state=open]:text-foreground [&>svg]:hidden">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="start">
                  {options.map((one) => (
                    <SelectItem key={`${one.provider_profile_id}:${one.model}`} value={`${one.provider_profile_id}:${one.model}`}>
                      {one.display_name || one.model}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </span>
          )}
          <button
            type="button"
            aria-label={t((item.text ?? "").trim() ? "boardRewrite" : "boardWrite")}
            title={`${t((item.text ?? "").trim() ? "boardRewrite" : "boardWrite")}  ⌘↵`}
            disabled={!prompt.trim() || !current || working}
            onClick={send}
            className={cn(
              "ml-auto grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors",
              !prompt.trim() || !current || working
                ? "cursor-not-allowed bg-secondary text-muted-foreground"
                : "cursor-pointer bg-primary text-primary-foreground hover:opacity-90",
            )}
          >
            {working ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={13} />}
          </button>
        </div>
      </div>
    </NodeToolbar>
  );
}
