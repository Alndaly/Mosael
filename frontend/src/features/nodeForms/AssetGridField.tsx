import React from "react";
import { closestCenter, DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, rectSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Image as ImageIcon, ImageOff, Link2, Plus, RotateCcw, Upload, Wand2, X } from "lucide-react";

import { assetThumbnailUrl, type Asset } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { useDndAccessibility } from "@/components/app/dndAccessibility";
import { AssetGridPicker, type GridAsset } from "@/components/app/AssetGridPicker";
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";
import {
  acceptFor,
  AssetUploadStatus,
  fileKind,
  namedFile,
  useAssetUpload,
  wrongKindText,
  type UploadKind,
} from "@/components/generation/assetUpload";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { hasReference } from "@/features/nodeForms/refDoc";
import { RefCombobox } from "@/features/nodeForms/RefCombobox";
import { parseIds } from "@/features/nodeForms/ScenePropsField";
import { useAssetDetails, useAssetSearch } from "@/lib/assetQueries";
import { assetKindKey } from "@/lib/assetKinds";
import { readSourceAssets, roleLabel, writeSourceAssets } from "@/lib/sourceAssetLines";
import { roleMedia, SOURCE_ROLES } from "@/lib/sourceFrames";
import { useFileDrop } from "@/lib/useFileDrop";
import { cn } from "@/lib/utils";

/**
 * **「一次挑一组素材」的那一格** —— 全仓只有这一个控件(后端声明点名 `editor: "asset_grid"`)。
 *
 * 形态(维护者拍板的样子):上传瓦片 + 「+」瓦片(从素材库挑)+ 一格一份缩略图;下面一行 chip 是
 * **运行时自动带进来的那些**(提示词里 `{{…}}` 引用到的素材,见 workflows/referencedImages);
 * 再下面是说明。挑、拖排序、直接传,不是一个手填引用的文本框。
 *
 * ## 值编码由**声明**决定(两种,别搞混)
 *
 * - **逗号分隔的素材 id 串**(默认:`image_asset_ids` / 实体保存 · 打标签 · 素材更新那三个 `asset_ids`):
 *   写回去的是一串 `a,b,c`。
 * - **一行一条 `素材id:角色`**(声明了 `lines: True` + `entry_labels: "source_roles"`:生成节点的
 *   「输入素材」):写回去的是**行的列表**(后端 `binding._source_lines` / `_line_asset_ids` 就是这么解的)。
 *   编码本身住在 `lib/sourceAssetLines`(唯一一份),这里只按 `lines` 选哪一半。
 *
 * ## 角色只从声明取
 *
 * 声明了 `entry_labels: "source_roles"` 的格子,每一份素材带一个角色(首帧 / 尾帧 / 参考图……):
 * 缩略图右下角一枚**角色角标**,点它换;自动来的那些 chip 里也有一枚(默认声明里那个 `ref_assets_role`)。
 * 角色词表**只此一份**(`lib/sourceFrames` 的 `SOURCE_ROLES` / `ROLE_COPY`)—— 这个控件不抄第二张,
 * 也就不可能和画布上的输入口、AI 工作台、画板的槽位叫出两个名字。没声明角色的格子
 * (那三个 `asset_ids`)根本不长角标。
 *
 * ## 哪些素材进得来:声明说了算
 *
 * `media` 声明了哪几类就只收哪几类(`["image"]` 只让图片进来);没声明的格子什么素材都收,按角色来的
 * 那些格子按**那个角色要的那一类**(`lib/sourceFrames.roleMedia`)—— 参考视频那一格收视频,首帧那一格收图。
 *
 * ## 自动来的那些(「引用即发送」)
 *
 * 提示词 / 系统提示词里 `{{…}}` 引用到的素材,运行时会自动并进这一格(后端 `binding.with_referenced_assets`,
 * 同一份声明 `ref_assets_from`)。它们和手动挑的**分开摆**在下面一行 chip 里,名字是引用(「画图 · 素材」)——
 * 来源看得见,不用去翻提示词。× 去掉一处 = 写进 `<字段>_excluded`(下一轮不会又塞回来),点回来即可恢复;
 * 带角色的格子还能改角色(记在 `<字段>_roles`),模型收不下这个角色时**明说**(声明里的 `ref_assets_gate`)。
 */

/** 一格 / 虚线操作格共用的骨架;高 48px 是内容不是控件(docs/DESIGN_LANGUAGE.md)。 */
const TILE_CLASS = "relative h-12 overflow-hidden rounded-lg border";
/** 带角色的瓦片高一点:角色角标要写下一个角色名(「参考图」/「Reference image」)并看得见。 */
const ROLE_TILE_CLASS = "relative h-16 overflow-hidden rounded-lg border";
/**
 * 一格里的瓦片**设计列数**(一排最多几列):带角色的**两列**(角色角标要写下一个角色名,四列一格
 * 放不下它),不带角色的**四列**(大模型那格一直就是这个样子)。
 *
 * 瓦片**不到**这个数时不是按它硬分列,而是按实际枚数分(见下面 `tileGrid`)—— 「同一行内尽量满宽」。
 * 多过这个数时就是它:八张图仍旧一排四张,不会撑成巨块。
 */
const ROLE_TILE_COLUMNS = 2;
const PLAIN_TILE_COLUMNS = 4;
/** 角标压在缩略图右下角:半透明深底 + 浅字,缩略图深浅都能读。 */
const BADGE_ON_TILE = "absolute bottom-0.5 right-0.5 max-w-[calc(100%-0.25rem)] overflow-hidden text-ellipsis border-transparent bg-[rgba(10,12,15,0.72)] text-[#e8eaed] backdrop-blur-sm hover:bg-[rgba(10,12,15,0.85)] hover:text-[#fff]";

/** 自动来的一处引用:给人看的名字 + 存进排除清单的记号(见 workflows/referencedImages)。 */
export interface AutoImageRef {
  /** 引用路径(`图.asset_id`)—— 排除清单里存的就是它。 */
  path: string;
  /** 给人看的名字(「画图 · 素材」)。 */
  label: string;
  /** 静态就知道是哪张素材时给出来;用来判它到底是不是这一格要的那类素材。 */
  assetId: string | null;
}

/**
 * 这一格认得的一个角色(由 `entry_labels: "source_roles"` 的声明取,见 lib/sourceFrames)。
 *
 * `accepted` / `limit` / `slots` 来自**选中的那个模型**(生成描述符),由宿主算好交下来 —— 控件不认识模型。
 */
export interface AssetGridRole {
  value: string;
  /** 界面上叫什么(已翻译)。 */
  label: string;
  /** 这个模型收不收它(声明 `ref_assets_gate` 那道闸);undefined = 还没认出模型,不下结论。 */
  accepted?: boolean;
  /** 这个角色最多挂几份(描述符 `source_limits`)。 */
  limit?: number;
  /** 这个角色的槽位按顺序叫什么(描述符 `source_labels`)。 */
  slots?: readonly string[];
}

/** 一格里的一份:值(素材 id、或一段 `{{…}}` 引用)+ 角色(没声明角色的格子恒为空串)。 */
interface Item {
  value: string;
  role: string;
}

/**
 * 宿主按**所选模型**算出来的角色事实(生成节点那一格):能力闸收不收、能挂几份、槽位叫什么。
 *
 * 控件不认识生成模型(它只是个格子),所以这几样由宿主算好交下来 —— 和 `autoImages` 同一种交法。
 * 判据本身仍来自声明:`ref_assets_gate` 点名哪道闸、`entry_labels` 点名角色词表。
 */
export interface AssetGridModel {
  /** 这个模型收得下的角色(那一道能力闸);**null = 还没认出模型**,不下结论。 */
  accepted: readonly string[] | null;
  /** 每个角色最多几份(描述符 `source_limits`)。 */
  limits?: Readonly<Record<string, number>>;
  /** 每个角色的槽位按顺序叫什么(描述符 `source_labels`)。 */
  slots?: Readonly<Record<string, readonly string[]>>;
}

/**
 * **声明 → 角色词表**:`entry_labels: "source_roles"` 的格子才长角色角标,词表就是 lib/sourceFrames
 * 那一份(和画布上的输入口、AI 工作台、画板的槽位同一张),模型收不收由宿主算的那个 `model` 说。
 */
export function assetGridRoles(
  declaredBy: unknown,
  model: AssetGridModel | undefined,
  t: (key: MessageKey) => string,
): readonly AssetGridRole[] | null {
  if (String(declaredBy ?? "") !== "source_roles") return null;
  return SOURCE_ROLES.map((role) => ({
    value: role,
    label: roleLabel(t, role),
    //: 认不出模型(`accepted` 没有 / 是 null)时**不下结论**:界面上不标、也不说它不收。
    accepted: model?.accepted === undefined || model.accepted === null ? undefined : model.accepted.includes(role),
    limit: model?.limits?.[role],
    slots: model?.slots?.[role],
  }));
}

/**
 * 这一格最多几份:带角色的格子按描述符给每个角色能挂几份**加起来**(海螺那种九张参考图的模型不能只让挑 8 张),
 * 没有角色的格子是 8(大模型节点那格一直就是 8)。
 */
export function assetGridMax(roles: readonly AssetGridRole[] | null): number {
  if (!roles || roles.length === 0) return 8;
  const usable = roles.filter((one) => one.accepted !== false);
  const total = usable.reduce((sum, one) => sum + Math.max(one.limit ?? 1, 1), 0);
  return total > 0 ? total : 8;
}

export function AssetGridField({
  value,
  workspaceId,
  onChange,
  lines = false,
  roles = null,
  media = null,
  defaultRole = "",
  max = 8,
  refs = [],
  excluded = [],
  onExcludedChange,
  roleOverrides = {},
  onRoleOverrideChange,
  variables = [],
}: {
  /** 逗号分隔的素材 id 串(**声明了 `lines` 时**是行的列表:一行一条 `素材id:角色`)。 */
  value: unknown;
  workspaceId: string;
  /** 写回新值:编码跟着 `lines` 走(列表 / 逗号分隔串)。 */
  onChange: (next: unknown) => void;
  /** 声明 `lines`:值是一行一条 `素材id:角色`(生成节点的「输入素材」)。 */
  lines?: boolean;
  /** 声明 `entry_labels: "source_roles"` 取出来的角色词表;不给 = 这一格没有角色。 */
  roles?: readonly AssetGridRole[] | null;
  /** 声明 `media`:只收这几类素材;不给 = 都收(带角色的格子按那个角色要的那一类)。 */
  media?: readonly string[] | null;
  /** 声明 `ref_assets_role`:自动来的那几份以什么角色发(也是新挑一份时的默认角色)。 */
  defaultRole?: string;
  /** 一格最多几份;满了上传格、素材库格就不出现。 */
  max?: number;
  /** 运行时自动带上来的那几处引用(空 = 这一格没有自动来的,整块不出现)。 */
  refs?: readonly AutoImageRef[];
  /** 已经点名不要的那几处引用(值存在 `<字段>_excluded` 那一格里)。 */
  excluded?: readonly string[];
  /** 改排除清单。不给就只能看不能改。 */
  onExcludedChange?: (next: string[]) => void;
  /** 自动来的那几处引用**改过**的角色(`引用路径 → 角色`,值存在 `<字段>_roles` 那一格里)。 */
  roleOverrides?: Readonly<Record<string, string>>;
  /** 改一处自动引用要用什么角色发。不给就只能看不能改。 */
  onRoleOverrideChange?: (path: string, role: string) => void;
  /** 能接的上游输出(`{{上游.输出}}`):给了才出现「再加一份」那一行(只有一行一项的格子要它)。 */
  variables?: readonly string[];
}) {
  const t = useI18n();
  const picked: Item[] = React.useMemo(
    () =>
      lines
        ? readSourceAssets(value)
        : (Array.isArray(value) ? value.map(String) : parseIds(String(value ?? "")))
            .filter(Boolean)
            .map((one) => ({ value: one, role: "" })),
    [value, lines],
  );
  //: 值里有 `{{…}}` 引用(上游输出、或一整组素材)时不去查它的详情:那不是素材 id。
  //: **自动来的那几份也要查**:静态就知道是哪一份、而它又不是这个角色要的那一类时,界面上要当场说明。
  const detailIds = React.useMemo(
    () => [
      ...new Set([
        ...picked.filter((one) => !hasReference(one.value)).map((one) => one.value),
        ...refs.map((one) => one.assetId).filter((id): id is string => Boolean(id)),
      ]),
    ],
    [picked, refs],
  );
  const details = useAssetDetails(detailIds);

  const roleAware = Boolean(roles && roles.length > 0);
  /** 这个模型收得下的角色(`ref_assets_gate` 那道闸,宿主按所选模型算);null = 还没认出模型,不下结论。 */
  const accepted = React.useMemo(() => {
    if (!roleAware) return null;
    const known = (roles ?? []).filter((one) => one.accepted !== undefined);
    if (known.length === 0) return null;
    return known.filter((one) => one.accepted).map((one) => one.value);
  }, [roleAware, roles]);
  //: 挑的时候列哪几种角色:认得出模型时是它收得下的那些,否则是声明里的全部(当前这个角色不收也列出来
  //: —— 换一个收得下的角色就能发,而角色不同结果完全不同)。
  const pickableRoles = React.useMemo(
    () => (accepted === null ? (roles ?? []) : (roles ?? []).filter((one) => accepted.includes(one.value))),
    [accepted, roles],
  );
  //: 一个角色都不收时(认不出的模型):挑的清单按声明里的全部算,别让整格变成点不动。
  const rolesForKinds = pickableRoles.length > 0 ? pickableRoles : (roles ?? []);

  /** 这一格收哪几类素材:声明优先,否则按角色(每个角色要的那一类),都没有就是什么都收。 */
  const allowedKinds = React.useMemo(() => {
    if (media && media.length > 0) return [...media];
    if (!roleAware) return null;
    return [...new Set(rolesForKinds.map((one) => roleMedia(one.value)))];
  }, [media, roleAware, rolesForKinds]);
  const kindAllowed = (kind: string) => !allowedKinds || allowedKinds.includes(kind);
  /** 一份素材放进这个角色合不合法(带角色的格子按那个角色要的那一类)。 */
  const kindAllowedFor = (kind: string, role: string) =>
    roleAware && role ? roleMedia(role) === kind : kindAllowed(kind);
  /** 新挑一份(素材库 / 上传)时它该挂哪个角色:那个角色要的那一类正好对得上,优先声明里的默认角色。 */
  const roleForKind = (kind: string): string => {
    if (!roleAware) return "";
    const fits = rolesForKinds.filter((one) => roleMedia(one.value) === kind).map((one) => one.value);
    return fits.includes(defaultRole) ? defaultRole : fits[0] ?? defaultRole;
  };
  const uploadAccept = allowedKinds ? allowedKinds.map((kind) => acceptFor(kind as UploadKind)).join(",") : acceptFor("media");
  const rejectKinds: UploadKind[] | "media" = allowedKinds ? (allowedKinds as UploadKind[]) : "media";

  /** 排好序的新值写回:声明了 `lines` 是行的列表,否则是逗号分隔的串。**编码只在这一处**。 */
  const write = (next: Item[]) => onChange(lines ? writeSourceAssets(next) : next.map((one) => one.value).join(","));

  //: upload 的 done 回调闭包要读到最新的 picked / 编码(传的间隙里值可能已变):render 时塞进 ref。
  const pickedRef = React.useRef(picked);
  pickedRef.current = picked;
  const writeRef = React.useRef(write);
  writeRef.current = write;

  const append = React.useCallback(
    (item: Item) => {
      //: 传的间隙里又挑了几张、满了:传完的那张留在素材库里,不硬塞进来。
      const current = pickedRef.current;
      if (current.length < max) writeRef.current([...current, item]);
    },
    [max],
  );

  //: 一次只传一个(useAssetUpload 的规矩),多文件排队:传完一个 done 再传下一个。
  const upload = useAssetUpload(workspaceId);
  const queueRef = React.useRef<File[]>([]);
  const [batch, setBatch] = React.useState({ total: 0, done: 0 });

  const pump = React.useCallback(() => {
    const next = queueRef.current.shift();
    if (!next) return;
    upload.start(namedFile(next), (asset: Asset) => {
      append({ value: asset.id, role: roleForKind(String(asset.kind ?? "")) });
      setBatch((batch) => ({ ...batch, done: batch.done + 1 }));
      pump();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upload, append]);

  const take = React.useCallback(
    (files: File[]) => {
      const ok = files.filter((file) => {
        const kind = fileKind(file);
        return kind !== null && kindAllowed(kind);
      });
      if (!ok.length) {
        if (files[0]) upload.reject(wrongKindText(t, files[0], rejectKinds));
        return;
      }
      const room = max - pickedRef.current.length - queueRef.current.length - (upload.state.status === "uploading" ? 1 : 0);
      if (room <= 0) {
        upload.reject(t("wfAssetGridMax").replace("{max}", String(max)));
        return;
      }
      queueRef.current.push(...ok.slice(0, Math.max(room, 0)));
      setBatch((batch) => ({ total: batch.total + Math.min(ok.length, Math.max(room, 0)), done: batch.done }));
      pump();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [max, upload, pump, t, allowedKinds],
  );

  /** 没传上/传完了:把排队和计数清掉(「取消」和「知道了」都走这里)。 */
  const clearQueue = React.useCallback(() => {
    queueRef.current = [];
    setBatch({ total: 0, done: 0 });
  }, []);
  const cancelUpload = React.useCallback(() => {
    upload.cancel();
    clearQueue();
  }, [upload, clearQueue]);
  const dismiss = React.useCallback(() => {
    upload.dismiss();
    clearQueue();
  }, [upload, clearQueue]);

  const drop = useFileDrop(take);
  const chooser = React.useRef<HTMLInputElement | null>(null);
  const [picking, setPicking] = React.useState(false);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const dndAccessibility = useDndAccessibility();
  const onDragEnd = (event: DragEndEvent) => {
    const over = event.over ? String(event.over.id) : null;
    if (!over) return;
    const from = picked.findIndex((one) => one.value === String(event.active.id));
    const to = picked.findIndex((one) => one.value === over);
    if (from < 0 || to < 0 || from === to) return;
    write(arrayMove(picked, from, to));
  };

  /** 一个角色在界面上叫什么;认不出的角色照原样写出来 —— 不静默换成别的词。 */
  const roleName = (role: string) => (roles ?? []).find((one) => one.value === role)?.label ?? role;

  const full = picked.length >= max;
  /** 这一格真画出来的瓦片数:已挑的 + 还没满时那两格虚线格(上传 / 从素材库挑)。 */
  const tiles = picked.length + (full ? 0 : 2);
  /** 这一格的设计列数:带角色两列、不带角色四列(见 ROLE_TILE_COLUMNS 上那段)。 */
  const tileColumns = roleAware ? ROLE_TILE_COLUMNS : PLAIN_TILE_COLUMNS;
  /**
   * 一排的排法 —— 「同一行内尽量满宽」这条版式**只有这一处**。
   *
   * 瓦片数不到设计列数时按**实际枚数**分列:`grid-flow-col auto-cols-fr` 让每一枚各占这一行的
   * 一等份。空格的常态正是两枚(上传格 + 「+」格),于是各半行、**整行占满那一格的宽度**;
   * 此前不带角色的格子写死 `grid-cols-4`,同样的两枚各占 25%、右边空出一截(大模型那格被报的)。
   * 到了设计列数以上就是那几列 —— 八张图仍旧一排四张,不会变成八个巨块。
   */
  const tileGrid =
    tiles <= tileColumns ? "grid-flow-col auto-cols-fr" : roleAware ? "grid-cols-2" : "grid-cols-4";
  return (
    <div className="relative" data-asset-grid="" data-asset-grid-mode={lines ? "lines" : "ids"} {...drop.handlers}>
      <DndContext
        sensors={sensors}
        accessibility={dndAccessibility}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        <SortableContext items={picked.map((one) => one.value)} strategy={rectSortingStrategy}>
          {/* 一排怎么分列见上面 `tileGrid`:瓦片不到设计列数时按实际枚数各占一等份(整行占满),
              到了以上就是设计列数。带角色的那一版**两列**的理由:角色角标要写下一个角色名
              (「参考图」/「Reference image」),四列一格(~80px)放不下它,而角色必须看得见。 */}
          <div className={cn("grid gap-1", tileGrid)}>
            {picked.map((item, index) => (
              <PickedTile
                key={item.value}
                id={item.value}
                index={index}
                asset={details.byId.get(item.value)}
                settled={details.settled}
                role={roleAware ? item.role : ""}
                roles={roleAware ? (roles ?? []) : []}
                wrongKind={
                  roleAware && item.role
                    ? details.byId.get(item.value) !== undefined &&
                      !kindAllowedFor(String(details.byId.get(item.value)?.kind ?? ""), item.role)
                    : false
                }
                onRoleChange={(role) =>
                  write(picked.map((one, at) => (at === index ? { ...one, role } : one)))
                }
                onRemove={() => write(picked.filter((_, at) => at !== index))}
              />
            ))}
            {/* 满 max 份:两格虚线格消失,格子就此定死(先移除再改)。 */}
            {!full && (
              <>
                {/* 虚线格的外壳是格子(高、圆角是内容的,不是控件的);整格可点的部分走 IconButton,名字只写一次。 */}
                <div className={cn(TILE_CLASS, "border-dashed bg-muted/40 text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground")}>
                  <IconButton
                    unstyled
                    data-upload-tile=""
                    label={t("wfAssetGridUpload")}
                    onClick={() => chooser.current?.click()}
                    className="grid size-full cursor-pointer place-items-center"
                  >
                    <Upload size={16} strokeWidth={1.8} />
                  </IconButton>
                </div>
                <div className={cn(TILE_CLASS, "border-dashed bg-muted/40 text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground")}>
                  <IconButton
                    unstyled
                    data-add-tile=""
                    label={t("wfAssetGridAdd")}
                    onClick={() => setPicking(true)}
                    className="grid size-full cursor-pointer place-items-center"
                  >
                    <Plus size={16} strokeWidth={1.8} />
                  </IconButton>
                </div>
              </>
            )}
          </div>
        </SortableContext>
      </DndContext>

      {/* 一行一项的格子:还能**手填一处上游输出**(整组素材、或上游那一刻给的那一份)—— 此前是按角色
          一条可手填的下拉,现在是一个「再加一份」的输入:挑完接在末尾、带上默认角色。 */}
      {lines && variables.length > 0 && !full && (
        <div className="mt-1.5 flex min-w-0 items-center gap-1.5" data-asset-grid-ref="">
          <Link2 size={11} strokeWidth={1.8} className="shrink-0 text-muted-foreground" />
          <RefCombobox
            value=""
            options={[]}
            literal={false}
            size="xs"
            variables={variables}
            placeholder={t("wfGenSourcePlaceholder")}
            onValueChange={(next: string) => {
              if (!next) return;
              write([...picked, { value: next, role: defaultRole }]);
            }}
          />
        </div>
      )}

      {/* 进度不占格子:下面一行小字。在传第 i 个 / 共 n 个;失败给重试/取消;收不了说为什么。 */}
      {upload.state.status === "uploading" && (
        <div role="status" data-asset-grid-upload="uploading" className="mt-1 flex min-w-0 items-center gap-1.5 text-ui-2xs text-muted-foreground">
          <Truncate className="min-w-0 flex-1">
            {t("wfAssetGridUploading")
              .replace("{name}", upload.state.name)
              .replace("{i}", String(Math.min(batch.done + 1, batch.total)))
              .replace("{n}", String(batch.total))}
          </Truncate>
          <IconButton
            size="icon-xs"
            variant="ghost"
            label={t("assetUploadCancel")}
            onClick={cancelUpload}
            className="shrink-0 text-muted-foreground"
          >
            <X size={11} />
          </IconButton>
        </div>
      )}
      {/* 没传上 / 收不了:那一句走 FailureCard 一行档(棘轮:design/failureDisplays.test.ts);重试、关掉摆在同行 —— */}
      {/* FailureCard 的 actions 收在「详情」浮层里,这种一行 alert 的地方要直接点得到(和 boards AssetUploadStatus 同一摆法)。 */}
      {(upload.state.status === "failed" || upload.state.status === "rejected") && (
        <div role="alert" data-asset-grid-upload={upload.state.status} className="mt-1 flex min-w-0 items-center gap-1 text-ui-2xs">
          <FailureCard
            size="inline"
            className="min-w-0 flex-1"
            title={upload.state.status === "failed" ? t("assetUploadFailedTitle") : t("assetUploadRejectedTitle")}
            {...rawFailureFields(
              upload.state.status === "failed"
                ? t("assetUploadFailed").replace("{name}", upload.state.name).replace("{reason}", upload.state.reason)
                : upload.state.message,
              upload.state.status === "failed" ? t("assetUploadFailedTitle") : t("assetUploadRejectedTitle"),
            )}
          />
          {upload.state.status === "failed" && (
            <Button size="xs" variant="ghost" data-upload-retry="" className="shrink-0 gap-1" onClick={upload.retry}>
              <RotateCcw size={11} />
              {t("retry")}
            </Button>
          )}
          <IconButton
            size="icon-xs"
            variant="ghost"
            label={t("close")}
            onClick={dismiss}
            className="shrink-0 text-muted-foreground"
          >
            <X size={11} />
          </IconButton>
        </div>
      )}

      {/* **自动来的那几处引用**(「引用即发送」):提示词 / 系统提示词里 `{{…}}` 引用到的素材,运行时会
          自动和提示词一起发出去(后端 binding.with_referenced_assets —— 同一份规则,这里只是把来源摆出来)。
          和上面手动挑的**分开**摆:看着名字就知道模型为什么会看到它,不用去翻提示词。
          × 去掉一处 = 写进 `<字段>_excluded`,运行时的取图认它;点回来即可恢复(不是删了就回不来)。
          带角色的格子还各有一枚角色角标:默认是声明里的那个,改过的记进 `<字段>_roles`。 */}
      {refs.length > 0 && (
        <div className="mt-1.5 grid gap-1" data-auto-images="">
          <div className="flex min-w-0 flex-wrap items-center gap-1">
            <span className="inline-flex shrink-0 items-center gap-1 text-ui-2xs font-medium text-muted-foreground">
              <Wand2 size={11} strokeWidth={1.8} />
              {t("wfAssetGridAutoTitle")}
            </span>
            {refs.map((ref) => {
              const on = !excluded.includes(ref.path);
              const role = roleAware ? roleOverrides[ref.path] || defaultRole : "";
              //: 这个模型收不下这个角色时明说(能力闸的判据和运行时同一份);认不出模型时不下结论。
              const rejected = on && roleAware && accepted !== null && !accepted.includes(role);
              //: 静态就知道是哪份素材时,顺手判一眼它是不是这个角色要的那一类 —— 不是的那些运行时会被跳过。
              const asset = ref.assetId ? details.byId.get(ref.assetId) : undefined;
              const wrongKind = asset !== undefined && !kindAllowedFor(String(asset.kind), role);
              return (
                <span
                  key={ref.path}
                  data-auto-image-ref={ref.path}
                  data-auto-image-on={on ? "true" : "false"}
                  data-auto-image-role={roleAware ? role : undefined}
                  className={cn(
                    "inline-flex min-w-0 items-center gap-1 rounded-full border py-px pl-2 pr-0.5 text-ui-2xs",
                    on ? "border-border bg-muted/40 text-foreground" : "border-dashed border-border text-muted-foreground",
                  )}
                >
                  <Truncate className="max-w-[9rem]" as="span">
                    {ref.label}
                  </Truncate>
                  {on && wrongKind && (
                    <span data-auto-image-skipped="" className="shrink-0 text-muted-foreground">
                      {t("wfGenAutoSourcesWrongKind").replace("{kind}", t(assetKindKey(String(asset?.kind ?? ""))))}
                    </span>
                  )}
                  {on && rejected && (
                    <span data-auto-image-rejected="" className="shrink-0 text-muted-foreground">
                      {t("wfGenAutoSourcesRejected").replace("{role}", roleName(role))}
                    </span>
                  )}
                  {on && roleAware && roles && roles.length > 0 && (
                    /* 角色改得动:改过的那个选择留下来,下一轮照它发(角色不同结果不同)。 */
                    <RoleBadge
                      role={role}
                      roles={roles}
                      onPick={(next) => onRoleOverrideChange?.(ref.path, next)}
                      label={t("wfGenSourceRole")}
                      className="shrink-0"
                    />
                  )}
                  <IconButton
                    size="icon-xs"
                    variant="ghost"
                    data-auto-image-toggle=""
                    label={(on ? t("wfAssetGridAutoDrop") : t("wfAssetGridAutoRestore")).replace("{name}", ref.label)}
                    onClick={() =>
                      onExcludedChange?.(
                        on ? [...excluded, ref.path] : excluded.filter((one) => one !== ref.path),
                      )
                    }
                    className="shrink-0 text-muted-foreground"
                  >
                    {on ? <X size={11} /> : <RotateCcw size={11} />}
                  </IconButton>
                </span>
              );
            })}
          </div>
          {/* 到顶了说清:自动来的也要占那 max 个位置,不然用户只会看到运行时一句「最多 N 份」。 */}
          {picked.length + refs.filter((one) => !excluded.includes(one.path)).length > max && (
            <p role="alert" data-auto-images-over="" className="text-ui-2xs text-destructive">
              {t("wfAssetGridAutoTooMany").replace("{max}", String(max))}
            </p>
          )}
          {/* 带角色的格子说清规矩:并进来的是这个角色要的那一类,模型收不下的角色不会被送进去。 */}
          <p className="text-ui-2xs leading-[1.5] text-muted-foreground">
            {roleAware ? t("wfGenAutoSourcesHint") : t("wfAssetGridAutoHint")}
          </p>
        </div>
      )}

      {/* 每个角色能挂几份、槽位按顺序叫什么(描述符的 source_limits / source_labels)—— 此前写在
          「按角色一行一格」那一行的标题里,现在角色是瓦片上的角标,这几句就摆在格子下面。 */}
      {roleAware && roles && roles.some((one) => (one.limit ?? 1) > 1 || (one.slots ?? []).length > 0) && (
        <div className="mt-1 grid gap-0.5" data-asset-grid-role-notes="">
          {roles.map((one) => {
            const notes: string[] = [];
            if ((one.limit ?? 1) > 1) notes.push(t("wfGenSourceMultiHint"));
            const names = (one.slots ?? []).map((name, index) => name || `#${index + 1}`);
            if (names.length > 0) notes.push(t("wfGenSourceSlotNames").replace("{names}", names.join(t("listSeparator"))));
            if (notes.length === 0) return null;
            return (
              <p key={one.value} data-role-note={one.value} className="text-ui-2xs leading-[1.5] text-muted-foreground">
                {one.label}
                {" · "}
                {notes.join(" · ")}
              </p>
            );
          })}
        </div>
      )}

      {/* 把文件拖到字段上任何一处都算数(不是某一个方框)。 */}
      {drop.active && (
        <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-lg border border-dashed border-primary bg-[color-mix(in_oklab,var(--primary)_8%,var(--background))]">
          <span className="inline-flex items-center gap-1.5 text-ui-2xs font-medium text-primary">
            <Upload size={12} />
            {t("boardsUploadDropHint")}
          </span>
        </div>
      )}

      <input
        ref={chooser}
        type="file"
        accept={uploadAccept}
        multiple
        hidden
        data-asset-grid-chooser=""
        onChange={(event) => {
          take(Array.from(event.target.files ?? []));
          event.target.value = "";
        }}
      />

      {picking && (
        <AssetGridDialog
          workspaceId={workspaceId}
          initial={picked.filter((one) => !hasReference(one.value)).map((one) => one.value)}
          max={max}
          kinds={allowedKinds}
          upload={upload}
          onClose={() => setPicking(false)}
          onConfirm={(chosen) => {
            //: 已经挑过的那几份**角色照旧**(弹窗里列的是素材库第一页,查不到种类的不能把角色丢了);
            //: 新挑的按素材种类给它该挂的那个角色(挑的顺序就是写回去的顺序)。
            const before = new Map(picked.map((one) => [one.value, one] as const));
            const manual = chosen.map((one) => before.get(one.id) ?? { value: one.id, role: roleForKind(one.kind) });
            //: 值里的 `{{…}}` 引用摆回它们原来的位置(弹窗里挑不了引用,也不该被挤到最后)。
            let at = 0;
            const kept = picked.map((one) => (hasReference(one.value) ? one : manual[at++] ?? null));
            write([...kept.filter((one): one is Item => one !== null), ...manual.slice(at)]);
            setPicking(false);
          }}
        />
      )}
    </div>
  );

}

/**
 * 一格的**角色角标**:点它换角色(只有声明了角色(`entry_labels: "source_roles"`)的格子才长它)。
 *
 * 词表就是交进来的那一份(声明 → lib/sourceFrames),这里不认第二张表。模型收不下的角色照样列出来
 * (换一个收得下的就能发),行尾标一句「这个模型不收」。
 */
function RoleBadge({
  role,
  roles,
  onPick,
  label,
  className,
}: {
  role: string;
  roles: readonly AssetGridRole[];
  onPick: (role: string) => void;
  /** 这枚角标叫什么(读屏;瓦片上的是「角色」,chip 里的是「以什么角色发」)。 */
  label: string;
  className?: string;
}) {
  const t = useI18n();
  const current = roles.find((one) => one.value === role);
  const shown = current?.label ?? t("wfAssetGridRoleNone");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Chip
          selected={false}
          data-role-badge={role}
          aria-label={`${label}: ${shown}`}
          onPointerDown={(event) => event.stopPropagation()}
          className={className}
        >
          {shown}
        </Chip>
      </PopoverTrigger>
      <MenuContent label={label} align="start">
        {roles.map((one) => (
          <MenuItem
            key={one.value}
            role="menuitemradio"
            checked={one.value === role}
            label={one.label}
            hint={one.accepted === false ? t("wfAssetGridRoleUnsupported") : undefined}
            onClick={() => onPick(one.value)}
          />
        ))}
      </MenuContent>
    </Popover>
  );
}

/** 一张已挑的素材:缩略图填满整格;悬停露右上角 ×;整格是拖柄;带角色的右下角是角色角标。 */
function PickedTile({
  id,
  index,
  asset,
  settled,
  role,
  roles,
  wrongKind,
  onRoleChange,
  onRemove,
}: {
  id: string;
  index: number;
  asset: Asset | undefined;
  settled: boolean;
  role: string;
  roles: readonly AssetGridRole[];
  wrongKind: boolean;
  onRoleChange: (role: string) => void;
  onRemove: () => void;
}) {
  const t = useI18n();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const [imgFailed, setImgFailed] = React.useState(false);
  //: 详情查得到 → 名字是它的;查不到(可能还没回来) → 先写 id。都 settled 了还没有 = 被删了。
  const asReference = hasReference(id);
  const missing = settled && !asset && !asReference;
  const failed = missing || imgFailed;
  const name = asset?.name || asset?.original_filename || id;
  const roleName = roles.find((one) => one.value === role)?.label;
  const hint = [
    missing ? t("wfAssetGridMissing") : name,
    roleName,
    wrongKind ? t("wfAssetGridWrongKind") : "",
  ].filter(Boolean).join(" · ");
  return (
    <Hint label={hint}>
      <div
        ref={setNodeRef}
        style={{ transform: CSS.Transform.toString(transform), transition }}
        {...attributes}
        {...listeners}
        data-asset-tile={id}
        data-asset-tile-role={role || undefined}
        data-dragging={isDragging}
        aria-label={missing ? `${name} · ${t("wfAssetGridMissing")}` : `${t("wfAssetGridImage")} ${index + 1}: ${name}`}
        className={cn(
          roles.length > 0 ? ROLE_TILE_CLASS : TILE_CLASS,
          "group cursor-grab touch-none border-border bg-panel-inset text-muted-foreground active:cursor-grabbing",
          isDragging && "z-20 opacity-70",
        )}
      >
        {failed ? (
          <span className="grid size-full place-items-center">
            <ImageOff size={14} strokeWidth={1.6} />
          </span>
        ) : asReference ? (
          //: 值是一段 `{{…}}` 引用(上游这一刻给的那一份、或一整组素材):没有缩略图可画。
          <span className="grid size-full place-items-center">
            <Link2 size={14} strokeWidth={1.6} />
          </span>
        ) : (
          <img
            src={assetThumbnailUrl(id)}
            alt=""
            loading="lazy"
            decoding="async"
            draggable={false}
            onError={() => setImgFailed(true)}
            className="absolute inset-0 size-full object-cover"
          />
        )}
        <IconButton
          unstyled
          label={t("wfAssetGridRemove").replace("{n}", String(index + 1))}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={onRemove}
          className="absolute right-0.5 top-0.5 z-10 grid size-5 cursor-pointer place-items-center rounded-full bg-[rgba(10,12,15,0.72)] text-[#e8eaed] opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
        >
          <X size={12} />
        </IconButton>
        {roles.length > 0 && (
          <RoleBadge role={role} roles={roles} onPick={onRoleChange} label={t("wfAssetGridRole")} className={BADGE_ON_TILE} />
        )}
      </div>
    </Hint>
  );
}

/**
 * 素材库挑素材弹窗(`AssetGridPicker` 的又一种用法:多选、先选再确认)。只列这一格收的那几类素材;
 * 选中的格子角标标先后 —— 挑的顺序就是写回去的顺序。上限 max:到顶再点没选中的格子不添(描述里写着上限)。
 * 打开时从当前值起选,确认把整份选择(按挑的顺序)写回 —— 所以在弹窗里也能去掉已挑的。
 */
function AssetGridDialog({
  workspaceId,
  initial,
  max,
  kinds,
  upload,
  onClose,
  onConfirm,
}: {
  workspaceId: string;
  initial: string[];
  max: number;
  /** 这一格收哪几类素材;null = 都收。 */
  kinds: readonly string[] | null;
  upload: ReturnType<typeof useAssetUpload>;
  onClose: () => void;
  onConfirm: (chosen: Array<{ id: string; kind: string }>) => void;
}) {
  const t = useI18n();
  const [chosen, setChosen] = React.useState(initial);
  const [justUploaded, setJustUploaded] = React.useState<Array<{ id: string; kind: string }>>([]);

  //: 素材库按这一格收的那几类筛(**没声明就不带这个筛**,什么素材都列);搜索、翻页交给
  //: useAssetSearch,和画板挑素材同一套。
  const library = useAssetSearch(
    { workspace_id: workspaceId, ...(kinds ? { kind: [...kinds] } : {}) },
    { enabled: true },
  );

  const chooser = React.useRef<HTMLInputElement | null>(null);
  //: 弹窗里传的,传完直接算「挑中了」—— 不用等素材库刷新完再让人找它。
  const take = (files: File[]) => {
    const file = files.find((one) => {
      const kind = fileKind(one);
      return kind !== null && (!kinds || kinds.includes(kind));
    });
    if (!file) {
      if (files[0]) upload.reject(wrongKindText(t, files[0], kinds ? (kinds as UploadKind[]) : "media"));
      return;
    }
    upload.start(namedFile(file), (asset: Asset) => setJustUploaded((ids) => [...ids, { id: asset.id, kind: String(asset.kind ?? "") }]));
  };
  const drop = useFileDrop(take);

  const items: readonly GridAsset[] = library.items;
  const narrowed = library.text.trim() !== "";
  const kindById = new Map<string, string>([
    ...items.map((one) => [one.id, String(one.kind)] as const),
    ...justUploaded.map((one) => [one.id, one.kind] as const),
  ]);
  //: 刚在弹窗里传完的那几张算「挑中了」,跟在已挑的后面(和挑的顺序一致,先挑的在前)。
  const all = [...chosen, ...justUploaded.map((one) => one.id).filter((id) => !chosen.includes(id))];
  const toggle = (asset: GridAsset) => {
    setChosen((current) => {
      if (current.includes(asset.id)) return current.filter((id) => id !== asset.id);
      //: 到顶再点没选中的:不添(也不把已选的踢掉)。
      if (current.length >= max) return current;
      return [...current, asset.id];
    });
  };

  return (
    <AssetGridPicker
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("wfAssetGridPickTitle")}
      description={t("wfAssetGridPickDesc").replace("{max}", String(max))}
      searchLabel={t("searchAssets")}
      query={library.text}
      onQueryChange={library.search}
      toolbar={
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => chooser.current?.click()}>
          <Upload />
          {t("wfAssetGridUpload")}
        </Button>
      }
      banner={<AssetUploadStatus upload={upload} />}
      dropzone={{
        handlers: drop.handlers,
        overlay: drop.active ? (
          <div className="pointer-events-none absolute inset-0 z-30 grid rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_8%,var(--background))] p-4">
            <div className="grid place-items-center rounded-lg border-2 border-dashed border-primary/70">
              <span className="inline-flex items-center gap-2 text-ui-sm font-semibold text-primary">
                <Upload size={16} />
                {t("boardsUploadDropHint")}
              </span>
            </div>
          </div>
        ) : null,
      }}
      items={items}
      onActivate={toggle}
      selection={{
        multiple: true,
        isSelected: (asset) => all.includes(asset.id),
        //: 没选中的给 -1:角标画的是 order + 1,-1 不画(见 AssetGridPicker 的格子)。
        order: (asset) => all.indexOf(asset.id),
      }}
      mixedKinds={(kinds?.length ?? 2) > 1}
      pending={library.isLoading}
      error={library.isError ? library.error.message : null}
      onRetry={() => void library.refetch()}
      onReachEnd={library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined}
      loadingMore={library.isFetchingNextPage}
      empty={
        narrowed
          ? { icon: null, title: t("studioNoMatches"), body: t("studioNoMatchesHint") }
          : {
              icon: <ImageIcon />,
              title: kinds?.length === 1 && kinds[0] === "image" ? t("boardsNoImages") : t("wfAssetGridNoMedia"),
              body: t("boardsPickEmptyHint"),
            }
      }
      footer={
        <div className="flex min-w-0 items-center gap-2">
          <Truncate className="min-w-0 flex-1 text-ui-xs text-muted-foreground">
            {t("wfAssetGridPickedCount").replace("{n}", String(all.length)).replace("{max}", String(max))}
          </Truncate>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            data-asset-grid-confirm=""
            //: 已经挑过的那几份,角色在上层按值查得到(查不到种类的也不丢);这里只报这一页查得到的种类。
            onClick={() => onConfirm(all.map((id) => ({ id, kind: kindById.get(id) ?? "" })))}
          >
            {t("wfAssetGridConfirm").replace("{n}", String(all.length))}
          </Button>
        </div>
      }
    />
  );
}
