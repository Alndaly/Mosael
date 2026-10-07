/**
 * 画板上选中一格时浮在它上面的操作条(ItemToolbar),和它用到的几枚小部件。
 * 从 BoardCanvas 拆出来:画布只管状态,操作条上按类型给哪些动作写在这里。
 */
import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { NodeToolbar, Position, type Node } from "@xyflow/react";
import { BookOpen, BookPlus, ChevronDown, Copy, FileOutput, NotebookPen, ExternalLink, Group, Maximize2, MoreHorizontal, PencilLine, Plus, Replace, Scissors, Sparkles, Trash2, type LucideIcon } from "lucide-react";

import { entityKeys, getEntity, type BoardItem, type BoardProducer, type BoardProducerInfo } from "@/api/client";
import { noteKeys } from "@/api/queryKeys";
import { errorText } from "@/api/errorMessage";
import { saveDocumentAsNote } from "@/api/domains/documents";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { ActionMenu } from "@/components/app/ActionMenu";
import { useImagePreview } from "@/components/app/image-preview";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { IconButton } from "@/components/ui/icon-button";
import { Hint, TooltipProvider } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { SaveToNote } from "@/features/notes/SaveToNote";
import { boardAbilities, boardToolIcon, DIRECT_ABILITIES, firstSentence, hostHasContent } from "@/features/boards/boardTools";
import { SequenceToolbarActions } from "@/features/boards/SequenceCell";
import { canAskWriter, canOpenOnDemand, slotProducers } from "@/features/boards/boardComposers";
import { NOTE_COLORS, noteColorClass, isMediaKind, kindIcon, SPAWNABLE_KINDS, type MediaKind, type NoteColor } from "@/features/boards/boardNodes";
import { itemIsRunning } from "@/features/boards/boardItemState";
import { boardPreviewGallery } from "@/features/boards/boardPreview";
import { useKeepInCanvas } from "@/features/boards/BoardComposerShell";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import type { BoardPickAsset } from "@/features/boards/boardCanvasModel";
import { entryOrigin, formedGroups } from "@/lib/entryNames";
import { cn } from "@/lib/utils";

/** 操作条上点开的那两块不是能力的面板。 */
export const WRITER_PANEL = "write";
export const TRIM_PANEL = "trim";
const SEQUENCE_EXPORT_PANEL = "sequence_export";

type GrowKind = (typeof SPAWNABLE_KINDS)[number];

/** 操作条上「接着做」的按钮按这个顺序排。 */
const GROW_ORDER: GrowKind[] = ["image", "video", "note", "audio"];

/**
 * 「接着做」:选中一格,能从它长出哪几种格子,悬停时各说什么。**一张表**,按(这一格的种类 → 长出的种类)查。
 *
 * 此前能长出哪几种是一串按种类的判断,悬停说明又另写一处,只分「便签 → 图片」和「其余 → 视频」两句 ——
 * 于是便签往下接视频时说「用这段文字生成图片」,文档往下接图片时说「用这张图当首帧生成视频」。
 * 便签、文档给的是文字:往下接图片、视频、音频(念出来)、文案;图片给首帧、视频给参考、音频给配乐:往下接视频;
 * 谁都能往下接一段文案。
 */
const GROW: Partial<Record<BoardItem["kind"], Partial<Record<GrowKind, MessageKey>>>> = {
  //: 便签不往下长「文案」:它自己就是一段文案,改写、翻译是它自己的能力(让 AI 写 / 翻译),再长出一张便签是第三个入口。
  note: { image: "boardSpawnImageFromNote", video: "boardSpawnVideoFromText", audio: "boardSpawnAudio" },
  document: { image: "boardSpawnImageFromNote", video: "boardSpawnVideoFromText", note: "boardSpawnNote", audio: "boardSpawnAudio" },
  image: { video: "boardSpawnVideoFromImage", note: "boardSpawnNote" },
  video: { video: "boardSpawnVideoFromVideo", note: "boardSpawnNote" },
  audio: { video: "boardSpawnVideoFromAudio", note: "boardSpawnNote" },
  //: 3D 场景给的是**场景**,不是一张图(ADR 0029):连进去的那一格面板上挑镜头和用法,生成时现渲。
  //: 不往下长文案 —— 场景格没有文字可接。
  scene: { image: "boardSpawnImageFromScene", video: "boardSpawnVideoFromScene" },
};

/**
 * 选中一项时浮在它上面的操作条。
 *
 * **按类型给动作,不给一套通用的**:便签要换颜色,图片/视频要换素材,分组框两者都不要。
 * 摆一排一半是灰的按钮,等于让用户每次都先分辨哪些能点。
 *
 * **中间那一段是这一格的能力**(TapNow 那样一排图标):看大图、剪一段、换一份、让 AI 写,再接这一格会的
 * 那几件事 —— 音频格的转写、分离、降噪,视频格的转 GIF,便签的翻译,插件工具按它吃什么内容挂上来
 * (后端 `role: "ability"` + `hosts`,见 boardTools.boardAbilities)。直接摆 DIRECT_ABILITIES 项,内置的在前,
 * 其余收进「⋯」。点一项,它的面板挂在格子下面;点另一项,下面那块换成它的;再点一次收起(BoardCanvas 的 panel)。
 *
 * 位置跟着选中项走 —— 用 NodeToolbar,它渲染在 React Flow 的视口层里,平移缩放时自己跟着动
 * (工作流那边的检查器用的是同一个原语)。
 */
export function ItemToolbar({
  nodes,
  setNodes,
  onRemoveSelected,
  onCopySelected,
  onRename,
  onPickAsset,
  onPickDocument,
  saveToNote,
  onSpawn,
  producers,
  panel,
  onPanel,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  /** 删掉选中的这几项 —— **连同挂在它们上面的线**。见 BoardCanvas 的 Inner 里的实现。 */
  onRemoveSelected: () => void;
  /** 复制选中的这几项(见 copySelected)。 */
  onCopySelected: () => void;
  /** 给这一格改名:打开它上方名字那一处的输入框(和双击名字是同一个状态)。 */
  onRename?: (itemId: string) => void;
  onPickAsset: BoardPickAsset;
  /** 给文档格挑一篇笔记(引用 / 换一篇)。评论、标记模式下不给。 */
  onPickDocument?: (itemId: string) => void;
  /** 便签「保存到笔记」存到哪、出处记哪张画板。评论、标记模式下不给。 */
  saveToNote?: { workspaceId: string; boardId: string };
  /** 从这一项长出下一项并连上。没给 = 这张画板不支持生成(上层没接生成能力)。 */
  onSpawn?: (
    kind: (typeof SPAWNABLE_KINDS)[number],
    from: string,
    at: { x: number; y: number },
    fromIsSource?: boolean,
  ) => void;
  /** 产出者清单:这一格有哪些能力、空槽能在哪几个产出者之间切(音频槽:配音 / 生成 / 插件的生成器)。 */
  producers?: BoardProducerInfo[];
  /** 此刻点开的那一块面板(让 AI 写、剪一段、一项能力)—— 按钮据此是按下态,再点一次收起。 */
  panel?: { itemId: string; name: string } | null;
  /** 打开 / 收起这一格的一块面板。没给 = 这张画板不能跑(上层没接产出者)。 */
  onPanel?: (itemId: string, name: string) => void;
}) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  // 标记不进这条操作条:它没有素材、不生成、不换一份,而这里每个动作都要读它没有的 item
  // (「复制一份」此前就会在这里抛)。它自己的改名/绑键/删除开在旗子上。
  const selected = nodes.filter((node) => node.selected && node.type !== "marker");
  // 多选时只给共通的动作 —— 逐个类型的动作在混选下没有一致的含义。
  const single = selected.length === 1 ? selected[0] : null;
  //: 操作条和面板一样,格子贴着画布边时不钻到侧栏底下(横向平移回来;它只有一行,不收高度)。
  const bar = React.useRef<HTMLDivElement | null>(null);
  const fit = useKeepInCanvas(bar, { vertical: false });
  //: 资产格的能力看它引用的是哪一种资产(人物才有「生成表情」)。和格子自己取的是同一份缓存。
  const singleData = single?.data as unknown as { item: BoardItem; workspaceId?: string } | undefined;
  const entityId = singleData?.item.kind === "entity" ? (singleData.item.entity_id ?? "") : "";
  const entityKind = useQuery({
    queryKey: entityKeys.detail(singleData?.workspaceId ?? "", entityId),
    queryFn: () => getEntity(entityId),
    enabled: Boolean(entityId),
    retry: false,
  }).data?.kind;
  const queryClient = useQueryClient();
  if (selected.length === 0) return null;
  const item = single ? (single.data as unknown as { item: BoardItem }).item : null;
  const patch = (id: string, next: Partial<BoardItem>) =>
    setNodes((current) =>
      current.map((node) =>
        node.id === id
          ? { ...node, data: { ...node.data, item: { ...(node.data as { item: BoardItem }).item, ...next } } }
          : node,
      ),
    );
  const open = (name: string) => Boolean(item && panel?.itemId === item.id && panel.name === name);
  const abilities = item && onPanel ? boardAbilities(item, producers, entityKind) : [];
  //: 直接摆几项;点开的那一项哪怕排在后面也摆出来(不然按下态藏在「⋯」里,看不出下面那块是谁的)。
  const direct = abilities.filter((one, index) => index < DIRECT_ABILITIES || open(one.id));
  const overflow = abilities.filter((one) => !direct.includes(one));
  //: 两层名字的副名(ADR 0045):这项能力是哪张工作流的哪个入口(「来自 X」/「完整工作流」),再接是哪个插件
  const formed = formedGroups(abilities);
  const sourceOf = (ability: BoardProducerInfo) =>
    [entryOrigin(ability.group, formed, t), ability.plugin_name].filter(Boolean).join(" · ");
  const slots = single && item && !itemIsRunning(item) ? slotProducers(item, producers) : [];
  //: 看大图看的是**选中的这几格**:框选了一排图,灯箱里就左右翻这一排(按画板上的位置排);只选一格就是那一张。
  const previews = boardPreviewGallery(selected.flatMap((node) => (node.data as { item?: BoardItem }).item ?? []));
  return (
    //: 上下浮层都从**节点边框**量同一段距离。类型标签挂在节点外,但不能因此让上方浮层
    //: 另用一套数字 —— 否则一眼看过去就是上疏下密。
    <NodeToolbar nodeId={selected.map((node) => node.id)} isVisible position={Position.Top} offset={BOARD_NODE_PANEL_OFFSET}>
      {/* 这条上几乎全是图标:名字靠悬停说明(Hint)。自己带一个 Provider —— 从一枚滑到下一枚时不再等一遍。 */}
      <TooltipProvider delayDuration={300} skipDelayDuration={400}>
      <div
        ref={bar}
        style={fit}
        className="nodrag nopan flex items-center gap-1 whitespace-nowrap rounded-full border border-floating-border bg-panel p-1.5 shadow-[var(--shadow-panel)]"
      >
        {/* 按类型来的几段各装在一格里,**分隔线是那一格自己的右边框**(ToolbarCluster)。于是它不可能在没有
            动作时出现 —— 此前那道线自己抄了一遍「上面有没有东西」的条件,加了音频节点之后就和实际渲染分了岔。 */}
        <ToolbarCluster>
          {item?.kind === "note" &&
            NOTE_COLORS.map((color) => (
              <IconButton
                unstyled
                key={color}
                type="button"
                label={t(NOTE_COLOR_LABEL[color])}
                aria-pressed={item.color === color}
                className={cn(
                  "h-6 w-6 cursor-pointer rounded-full border transition-transform hover:scale-110",
                  noteColorClass(color),
                  item.color === color && "ring-2 ring-primary ring-offset-1 ring-offset-[var(--panel)]",
                )}
                onClick={() => patch(item.id, { color })}
              />
            ))}
          {/* 分组框:**这一组是不是一个整体**。开着的时候拖框会把框里的东西一起带走 ——
              没有它的话,想把一组想法整体挪个位置就得一个个拖。 */}
          {item?.kind === "frame" && (
            <Hint label={t(item.move_children ? "boardMoveChildrenOn" : "boardMoveChildrenOff")}>
            <button
              type="button"
              aria-pressed={Boolean(item.move_children)}
              className={cn(
                "flex cursor-pointer items-center gap-1.5 shrink-0 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs transition-colors",
                item.move_children
                  ? "bg-primary/12 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
              onClick={() => patch(item.id, { move_children: !item.move_children })}
            >
              <Group size={13} /> {t("boardMoveChildren")}
            </button>
            </Hint>
          )}
        </ToolbarCluster>

        {/* 这一格的能力:一排图标,名字在悬停和读屏里。 */}
        <ToolbarCluster data-board-abilities="">
          {/* 预览:**看大图是一个明确的动作,不是点在图上的副作用**。画布上点一下的意思是
              选中这个节点 —— 让图片自己接管点击的话,操作条和表单都弹不出来。 */}
          {/* 视频走同一个灯箱,只是那一项渲染成播放器 —— 见 image-preview。 */}
          {previews.length > 0 && (
            <ToolbarIcon
              name="preview"
              icon={Maximize2}
              label={t("boardPreview")}
              hint={t("boardPreviewTitle")}
              onClick={() => openImagePreview({ ...previews[0], gallery: previews })}
            />
          )}
          {/* 剪一段:视听素材才有时间轴,一张图截不出「第 3 秒」。 */}
          {onPanel && item?.asset_id && (item.kind === "video" || item.kind === "audio") && (
            <ToolbarIcon
              name="trim"
              icon={Scissors}
              label={t("boardTrim")}
              hint={t("boardTrimTitle")}
              pressed={open(TRIM_PANEL)}
              onClick={() => onPanel(item.id, TRIM_PANEL)}
            />
          )}
          {/* 在跑的格子不给换:产出归服务端,本地换上的素材会在保存时被丢掉、再被回滚(见 serverOwnedPatch),
              看起来就是换上的那份悄悄消失了。和「生成」、切换产出者同一条。 */}
          {item && isMediaKind(item.kind) && !itemIsRunning(item) && (
            <ToolbarIcon
              name="replace"
              icon={Replace}
              label={t("boardReplaceAsset")}
              onClick={() =>
                onPickAsset(item.kind as MediaKind, (assetId) =>
                  // 手动换素材不是上一轮 AI 任务的“成功产物”。把运行态归回 idle，同时 asset_id
                  // 变化会让对应 Composer 从节点表单重新水合，清掉上一轮局部 touched/submitting。
                  patch(item.id, { asset_id: assetId, run: { status: "idle" } }),
                )
              }
            />
          )}
          {/* 文档格引用哪一篇笔记:**操作条上的一个动作**,不是点格子的副作用 —— 点格子是选中它(拖、连线、
              让 AI 写都从选中开始)。还没引用时叫「引用笔记」,引用着的叫「换一篇」。 */}
          {/* 引用文档素材的文档格(ADR 0031):「转为笔记」把全文存成一篇笔记,这一格原地换成引用它 —— 从此能改、能让 AI 写。 */}
          {single && item?.kind === "document" && item.asset_id && !item.note_id && (
            <ToolbarIcon
              name="document-to-note"
              icon={NotebookPen}
              label={t("docSaveAsNote")}
              onClick={() => {
                const assetId = item.asset_id ?? "";
                void saveDocumentAsNote(assetId)
                  .then((made) => {
                    void queryClient.invalidateQueries({ queryKey: noteKeys.everywhere() });
                    patch(item.id, { note_id: made.note_id, note_revision: 1, asset_id: undefined, text: made.title,
                                     form: { ...item.form, producer: "write" } });
                  })
                  .catch((error: unknown) => toast.error(errorText(error)));
              }}
            />
          )}
          {/* 便签「保存到笔记」:和文档格的「转为笔记」同一种挂法 —— 操作条上的一个动作,只在单选时给。
              此前它挂在便签格子外面,多选几张便签就各冒一颗按钮,而操作条上什么都没有。
              没有字的便签不给:存不出东西。 */}
          {single && item?.kind === "note" && saveToNote && item.text?.trim() && (
            <SaveToNote
              workspaceId={saveToNote.workspaceId}
              content={item.text}
              sources={[{ kind: "board", id: saveToNote.boardId, label: t("navBoards"), quote: item.text }]}
              trigger={({ open: openDialog, label }) => (
                <ToolbarIcon name="note-to-note" icon={BookPlus} label={label} onClick={openDialog} />
              )}
            />
          )}
          {single && item?.kind === "document" && !item.asset_id && onPickDocument && (
            <ToolbarIcon
              name="pick-document"
              icon={item.note_id ? Replace : BookOpen}
              label={t(item.note_id ? "documentReplace" : "documentPick")}
              onClick={() => onPickDocument(item.id)}
            />
          )}
          {/* 让 AI 写:**明确的一个动作**,不是选中的副作用(见 BoardCanvas 的 Inner 的 panel)。能力交回的结构化数据
              (JSON 便签)不给 —— 那是一份数据,不是一段要改写的文案。 */}
          {single && item && onPanel && canAskWriter(item) && (
            <ToolbarIcon
              name="write"
              icon={Sparkles}
              label={t("boardAskAiWrite")}
              hint={t("boardAskAiWriteTitle")}
              pressed={open(WRITER_PANEL)}
              onClick={() => onPanel(item.id, WRITER_PANEL)}
            />
          )}
          {single && item && onPanel &&
            direct.map((ability) => (
              <ToolbarIcon
                key={ability.id}
                name={ability.id}
                ability
                icon={boardToolIcon(ability)}
                label={ability.label}
                hint={[entryOrigin(ability.group, formed, t), firstSentence(ability.board_description ?? "")].filter(Boolean).join(" · ")}
                pressed={open(ability.id)}
                onClick={() => onPanel(item.id, ability.id)}
              />
            ))}
          {single && item && onPanel && overflow.length > 0 && (
            <ActionMenu
              label={t("boardMoreAbilities")}
              trigger={<MoreButton label={t("boardMoreAbilities")} />}
              actions={overflow.map((ability) => {
                const Icon = boardToolIcon(ability);
                return {
                  label: ability.label,
                  icon: <Icon size={14} />,
                  hint: sourceOf(ability) || undefined,
                  onSelect: () => onPanel(item.id, ability.id),
                };
              })}
            />
          )}
        </ToolbarCluster>

        {/* 空槽用什么产出:一种格子有几个能填空槽的产出者时(音频槽:配音 / 生成音乐音效;插件的生成器)给一个切换。
            **只换表单上写的那个产出者**,面板随之换成它的;在跑的时候不给换。内置的和此刻选着的那个摆在外面,
            别的生成器收进「⋯」。 */}
        {single && item && slots.length > 0 && (
          <ToolbarCluster>
            <SlotSwitch item={item} slots={slots} onSwitch={(producer) => patch(item.id, { form: { ...item.form, producer } })} />
          </ToolbarCluster>
        )}

        {/* 从这一项长出下一项:**放一个空节点并连上,不是直接开跑**。空节点一选中它的面板就开着,
            用户还能改模型、改比例、再挂张参考图 —— 点一下就把任务发出去的话,这些他一个都来不及说。
            长出哪几种、每一个悬停时说什么,是同一张表(GROW);图标是要长出来的那种格子的图标,
            一眼看出这一下会多出一张图、一段视频还是一张便签。已经在跑的那一项不给(它还没有产出)。
            前面一个淡淡的「生成」,后面每一枚只写要长出来的那种东西(图片、视频、文案、音频)。 */}
        {onSpawn && single && item && !itemIsRunning(item) && hostHasContent(item) && GROW_ORDER.some((kind) => GROW[item.kind]?.[kind]) && (
          <ToolbarCluster>
            <ActionMenu
              label={t("boardGrowLabel")}
              align="start"
              trigger={
                <button
                  type="button"
                  aria-label={t("boardGrowLabel")}
                  aria-haspopup="menu"
                  data-board-grow-menu=""
                  className="flex shrink-0 cursor-pointer items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground data-[state=open]:bg-secondary data-[state=open]:text-foreground"
                >
                  <Plus size={13} /> {t("boardGrowLabel")} <ChevronDown size={12} className="opacity-60" />
                </button>
              }
              actions={GROW_ORDER.filter((kind) => GROW[item.kind]?.[kind]).map((kind) => {
                const Icon = kindIcon(kind);
                return {
                  //: 每一行把这一下说全(「用这张图当首帧生成视频」),不是光秃秃的「视频」—— 菜单里有地方写,
                  //: 而同一个「视频」从便签、图片、音频长出来是三件不同的事。
                  label: t(GROW[item.kind]?.[kind] as MessageKey),
                  icon: <Icon size={14} />,
                  onSelect: () =>
                    onSpawn(kind, item.id, {
                      x: single.position.x + (single.width ?? 260) + 60,
                      y: single.position.y + (single.height ?? 180) / 2,
                    }),
                };
              })}
            />
          </ToolbarCluster>
        )}

        {/* 去编辑器改这个场景。**入口挂在格子上,不挂在面板里** —— 面板随挑的那一种填法换(渲白模 / 按文字搭),
            此前它只在「渲白模参考」的面板头上,切到「按文字搭」就找不到了(用户截图)。 */}
        {single && item?.kind === "scene" && item.scene_id && (
          <Hint label={t("boardSceneOpen")}>
            <a
              aria-label={t("boardSceneOpen")}
              data-board-scene-open=""
              href={`#/scenes?scene=${encodeURIComponent(item.scene_id)}`}
              className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <ExternalLink size={13} />
            </a>
          </Hint>
        )}
        {/* 时间线格(ADR 0030)的剪刀、删除、在剪辑里打开 —— 放在操作条上,不占格子里的地方(用户:「这些按钮放到上方弹窗中去」)。 */}
        {single && item?.kind === "sequence" && item.sequence_id && (
          //: 自成一段(右边一道分隔线):「删掉这一段」和格子自己的「删除」是两个垃圾桶,挨在一起分不清删的是什么。
          <ToolbarCluster data-board-sequence-actions="">
          <SequenceToolbarActions
            sequenceId={item.sequence_id}
            button={({ label, icon, onClick, disabled, disabledReason, href, marker }) =>
              href !== undefined ? (
                <Hint key={marker} label={label}>
                  <a aria-label={label} data-board-sequence-action={marker} href={href}
                     className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground">
                    {icon}
                  </a>
                </Hint>
              ) : (
                <IconButton key={marker} unstyled type="button" label={label} data-board-sequence-action={marker}
                        disabled={disabled} disabledReason={disabledReason} onClick={onClick}
                        className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent">
                  {icon}
                </IconButton>
              )}
          />
          {/* 导出:打开导出面板(按需的面板,面板名就是产出者的名字)。成片落成右边一格视频。 */}
          {onPanel && canOpenOnDemand(item) && (
            <ToolbarIcon
              name="sequence-export"
              icon={FileOutput}
              label={t("boardSequenceExport")}
              hint={t("boardSequenceExportHint")}
              pressed={open(SEQUENCE_EXPORT_PANEL)}
              onClick={() => onPanel(item.id, SEQUENCE_EXPORT_PANEL)}
            />
          )}
          </ToolbarCluster>
        )}
        {/* 改名只对一格有意义 —— 多选时一起改成同一个名字,等于让它们重新分不清。 */}
        {single && item && onRename && (
          <IconButton
            unstyled
            type="button"
            label={t("rename")}
            className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
            onClick={() => onRename(item.id)}
          >
            <PencilLine size={13} />
          </IconButton>
        )}
        <IconButton
          unstyled
          type="button"
          label={t("copy")}
          className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground"
          onClick={onCopySelected}
        >
          <Copy size={13} />
        </IconButton>
        <IconButton
          unstyled
          type="button"
          label={t("delete")}
          className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground hover:text-destructive"
          onClick={onRemoveSelected}
        >
          <Trash2 size={13} />
        </IconButton>
      </div>
      </TooltipProvider>
    </NodeToolbar>
  );
}

/** 操作条上的一段:空着就不占地方,有东西时右边一道分隔线(那一格自己的右边框)。 */
function ToolbarCluster({ children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className="flex items-center gap-0.5 empty:hidden [&:not(:empty)]:mr-1 [&:not(:empty)]:border-r [&:not(:empty)]:border-border [&:not(:empty)]:pr-1.5"
    >
      {children}
    </div>
  );
}

/**
 * 操作条上的一枚图标按钮:看大图、剪一段、换一份、让 AI 写,和这一格的每一项能力,都是这一个样子 ——
 * 图标、名字在悬停和读屏里(`aria-label`),点开了一块面板的那一枚是按下态。
 */
function ToolbarIcon({
  name,
  icon: Icon,
  label,
  hint,
  pressed,
  ability = false,
  onClick,
}: {
  name: string;
  icon: LucideIcon;
  label: string;
  hint?: string;
  pressed?: boolean;
  /** 这一枚是这一格的一项能力(`data-board-ability`,测试和样式的钩子)。 */
  ability?: boolean;
  onClick: () => void;
}) {
  return (
    <IconButton
      unstyled
      type="button"
      label={label}
      hint={hint}
      aria-pressed={pressed === undefined ? undefined : pressed}
      data-board-action={ability ? undefined : name}
      data-board-ability={ability ? name : undefined}
      className={cn(
        "grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full transition-colors hover:bg-secondary hover:text-foreground",
        pressed ? "bg-secondary text-foreground" : "text-muted-foreground",
      )}
      onClick={onClick}
    >
      <Icon size={14} />
    </IconButton>
  );
}

/** 便签颜色的名字(色块本身没有字,读屏和悬停都靠它)。 */
const NOTE_COLOR_LABEL: Record<NoteColor, MessageKey> = {
  yellow: "boardNoteColorYellow",
  blue: "boardNoteColorBlue",
  green: "boardNoteColorGreen",
  pink: "boardNoteColorPink",
  purple: "boardNoteColorPurple",
  gray: "boardNoteColorGray",
};

/** 操作条上的「⋯」:和别的图标同一个尺寸、同一种悬停说明(ActionMenu 自带的那颗是 Button 档位的)。 */
const MoreButton = React.forwardRef<HTMLButtonElement, { label: string } & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "title" | "aria-label">>(
  ({ label, className, ...rest }, ref) => (
    <IconButton
      unstyled
      ref={ref}
      type="button"
      label={label}
      aria-haspopup="menu"
      {...rest}
      className={cn(
        "grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground data-[state=open]:bg-secondary data-[state=open]:text-foreground",
        className,
      )}
    >
      <MoreHorizontal size={14} />
    </IconButton>
  ),
);
MoreButton.displayName = "MoreButton";

/** 空槽上摆在外面的产出者:内置的(配音、生成)和此刻选着的那一个;插件的生成器多了收进「⋯」。 */
const SLOT_INLINE = 3;

/**
 * 空槽用什么产出的切换。内置的写名字(「配音」「生成」),插件的生成器带它的图标;多出来的收进「⋯」。
 * 选中的那一个是按下态,换一个只换表单上写的产出者(面板随之换成它的)。
 */
function SlotSwitch({
  item,
  slots,
  onSwitch,
}: {
  item: BoardItem;
  slots: BoardProducerInfo[];
  onSwitch: (producer: BoardProducer) => void;
}) {
  const t = useI18n();
  const current = item.form?.producer;
  const inline = slots.filter((one, index) => index < SLOT_INLINE || one.id === current);
  const more = slots.filter((one) => !inline.includes(one));
  const formed = formedGroups(slots);
  const sourceOf = (one: BoardProducerInfo) => [entryOrigin(one.group, formed, t), one.plugin_name].filter(Boolean).join(" · ");
  return (
    <>
      <div role="radiogroup" aria-label={t("boardProducerSwitch")} className="flex items-center gap-0.5 rounded-full bg-secondary/60 p-0.5">
        {inline.map((one) => {
          const on = current === one.id;
          const Icon = one.id.startsWith("node:") ? boardToolIcon(one) : null;
          return (
            <Hint key={one.id} label={one.label}
                  hint={[entryOrigin(one.group, formed, t), firstSentence(toPlainText(one.board_description || one.description || ""))]
                    .filter(Boolean).join(" · ")}>
            <button
              type="button"
              role="radio"
              aria-checked={on}
              className={cn(
                "flex max-w-40 cursor-pointer items-center gap-1 rounded-full px-2.5 py-1 text-ui-xs transition-colors",
                on ? "bg-panel text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => onSwitch(one.id as BoardProducer)}
            >
              {Icon ? <Icon size={12} className="shrink-0" /> : null}
              <Truncate>{one.label}</Truncate>
            </button>
            </Hint>
          );
        })}
      </div>
      {more.length > 0 && (
        <ActionMenu
          label={t("boardMoreGenerators")}
          trigger={<MoreButton label={t("boardMoreGenerators")} />}
          actions={more.map((one) => {
            const Icon = boardToolIcon(one);
            return { label: one.label, icon: <Icon size={14} />, hint: sourceOf(one) || undefined, onSelect: () => onSwitch(one.id as BoardProducer) };
          })}
        />
      )}
    </>
  );
}
