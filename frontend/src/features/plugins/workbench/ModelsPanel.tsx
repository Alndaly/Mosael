import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Info, Loader2, MousePointerClick, RefreshCcw } from "lucide-react";

import { getNodeFolders, modelPreviewUrl, type ModelFile } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { useImagePreview } from "@/components/app/image-preview";
import { ModelPreviewSettingsButton } from "@/components/generation/ModelPreviewSettingsButton";
import { ModelThumb, NsfwMark, PreviewOriginMark, modelBaseName, modelSubFolder } from "@/components/generation/ModelThumb";
import { previewPick, previewTreatment, useModelPreviewSettings } from "@/components/generation/modelPreviewSettings";
import { useModelLibrary } from "@/components/generation/useModelLibrary";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { SearchInput } from "@/components/ui/search-input";
import { OverChromeModals } from "@/components/ui/overChromeModal";
import { Truncate } from "@/components/ui/truncate";
import { EncoderRecipeMark } from "@/features/plugins/ModelEncoder";
import { ModelDetail, useModelActionsHost } from "@/features/plugins/ModelDetail";
import { ModelActionsContext } from "@/features/plugins/modelActions";
import { ModelContextMenu } from "@/features/plugins/ModelMenu";
import { ModelDownload } from "@/features/plugins/workbench/ModelDownload";
import {
  byRecipe,
  comboInputs,
  folderFamilies,
  folderModels,
  modelSlots,
  presentIn,
  type ModelSlot,
  type WorkbenchNode,
} from "@/features/plugins/workbench/workbenchLogic";
import { PANEL_ROOT, PanelEmpty, PanelLoading, PanelNote } from "@/features/plugins/workbench/workbenchParts";
import { workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { cn } from "@/lib/utils";

/** 一次最多摆多少个(一个目录里见过几百个 LoRA):多了先搜。 */
const LISTED = 120;

const keyOf = (model: { folder: string; name: string }) => `${model.folder}/${model.name}`;

/** 开着的详情:哪个文件、直接跳到哪一节;`open` 落成 false 之后还留着这一项,收起的动画里内容不先变空。 */
type DetailState = { key: string; section: "used" | null; open: boolean };

/**
 * 工作台的「模型库」面板(ADR 0038 §6):在画布上选中一个加载节点 → 问插件它那几格选的是哪个模型目录的文件 → 用模型库的数据
 * 只列那个目录的(缩略图、底模家族、触发词),能搜、能按家族筛 → 点一张卡,经桥填进那一格(桥先查它在下拉里);点缩略图看大图。
 * 现在那一格选的文件这台 ComfyUI 上没有,就地找下载地址或贴链接下到那个目录;下完经桥刷新下拉,新文件出现在下拉里。
 *
 * **卡片网格**:面板这一列会被拖宽拖窄,列表是多列卡(`auto-fill` + `minmax`,列数跟着容器宽度自己变,不写断点)。每张卡
 * 上面是填满卡宽的 4:3 缩略图(图片 object-cover,不按原图比例撑高),下面是名字与 meta 行;ⓘ 压在缩略图右上角、✓/转圈压在
 * 右下角,两者对角、不重叠。
 *
 * **看详情**(和模型库点开一张卡是同一页,见 ModelDetail):每一张卡悬停 / 聚焦时露出「查看详情」,右键是模型库那一份菜单
 * (第一项「查看详情」);详情开成一个大弹窗(这一列太窄),压在外壳之上、请画布让开(见 overChromeModal)。菜单和详情里的
 * 本事(在 Civitai 上找、存为预览图、标 NSFW、看大图……)和模型库同一份(useModelActionsHost)。关上之后焦点回到那张卡。
 */
export function ModelsPanel({
  target,
  node,
  capabilities,
}: {
  target: WorkbenchTarget;
  node: WorkbenchNode | null;
  capabilities: ComfyWorkbenchState["capabilities"] | null;
}) {
  const t = useI18n();
  const inputs = React.useMemo(() => comboInputs(node), [node]);
  const folders = useQuery({
    queryKey: ["comfy-node-folders", target.instanceId, JSON.stringify(inputs)],
    queryFn: () => getNodeFolders(target.instanceId, inputs),
    enabled: inputs.length > 0,
    staleTime: Infinity,
  });
  const library = useModelLibrary(target.instanceId, { staleTime: 30_000 });
  const slots = modelSlots(node, folders.data?.folders ?? [], folders.data?.encoders ?? []);
  const models = React.useMemo(() => library.data?.models ?? [], [library.data]);
  //: 「看大图」能跟着翻的:这几格的目录里的
  const slotFolders = slots.map((slot) => slot.folder).join("|");
  const shown = React.useMemo(() => {
    const wanted = new Set(slotFolders.split("|"));
    return models.filter((model) => wanted.has(model.folder));
  }, [models, slotFolders]);
  const [detail, setDetail] = React.useState<DetailState | null>(null);
  const host = useModelActionsHost({
    instanceId: target.instanceId,
    instanceName: target.instanceName,
    workspaceId: target.workspaceId,
    queryKey: library.queryKey,
    shown,
    tools: library.data?.preview_tools,
    onOpen: (model, section) => setDetail({ key: keyOf(model), section, open: true }),
  });
  const detailModel = detail ? models.find((model) => keyOf(model) === detail.key) ?? null : null;

  let body: React.ReactNode;
  if (capabilities && (!capabilities.selection || !capabilities.setWidget)) {
    body = <PanelNote tone="warning">{t("workbenchUnsupported").replace("{what}", t("workbenchCapSelection"))}</PanelNote>;
  } else if (!node) {
    body = <PanelEmpty icon={MousePointerClick}>{t("workbenchModelsPick")}</PanelEmpty>;
  } else if (folders.isPending && inputs.length > 0) {
    body = <PanelLoading label={t("workbenchModelsLoading")} />;
  } else if (folders.isError) {
    body = <PanelNote tone="error">{errorText(folders.error)}</PanelNote>;
  } else if (slots.length === 0) {
    body = <PanelEmpty icon={MousePointerClick}>{t("workbenchModelsNoSlot").replace("{node}", node.title || node.type)}</PanelEmpty>;
  } else {
    body = (
      <div className={cn(PANEL_ROOT, "gap-4")}>
        {slots.map((slot) => (
          <SlotPicker
            key={`${node.id}:${slot.widget}`}
            target={target}
            node={node}
            slot={slot}
            models={models}
            loading={library.isPending}
            error={library.isError ? errorText(library.error) : ""}
            canRefresh={capabilities?.refreshCombos !== false}
          />
        ))}
      </div>
    );
  }
  return (
    <ModelActionsContext.Provider value={host.actions}>
      {body}
      {/* 这里打开的弹窗(详情、「存为预览图」的确认)压在外壳之上、请画布让开 */}
      <OverChromeModals.Provider value>
        {host.dialogs}
        {detail && detailModel && (
          <ModelDetailDialog
            target={target}
            model={detailModel}
            section={detail.section}
            open={detail.open}
            onClose={() => setDetail((current) => (current ? { ...current, open: false } : current))}
            onClosed={() => {
              const key = detail.key;
              setDetail(null);
              //: 焦点回到那一行(它的「查看详情」):从右键菜单打开的,菜单那一项已经没了
              document.querySelector<HTMLElement>(`[data-model-detail="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
            }}
          />
        )}
      </OverChromeModals.Provider>
    </ModelActionsContext.Provider>
  );
}

/**
 * 工作台里一个模型的详情:模型库点开一张卡的那一页(ModelDetail),开成一个大弹窗 —— 这一列太窄,详情是两栏的。头上那颗
 * 「返回」在这里是「关闭详情」。预览图照模型库那两组设置(模糊、NSFW)。
 */
function ModelDetailDialog({
  target,
  model,
  section,
  open,
  onClose,
  onClosed,
}: {
  target: WorkbenchTarget;
  model: ModelFile;
  section: "used" | null;
  open: boolean;
  onClose: () => void;
  onClosed: () => void;
}) {
  const t = useI18n();
  const [previewSettings] = useModelPreviewSettings();
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        showClose={false}
        aria-describedby={undefined}
        data-workbench-model-detail=""
        //: 上边距 pt-6 和左右的 px-6 一样:详情的固定头(DETAIL_HEAD)只有左右和下边距,上边距本来由弹窗的标题栏给 ——
        //: 模型库的弹窗有那条标题栏,这里没有,名字和按钮就贴着弹窗的上沿(维护者截图)
        className="flex h-[min(860px,calc(100dvh-3rem))] w-[min(1180px,calc(100vw-3rem))] max-w-[calc(100vw-3rem)] flex-col gap-0 overflow-hidden p-0 pt-6"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          onClosed();
        }}
      >
        <DialogTitle className="sr-only">{model.title || modelBaseName(model.name)}</DialogTitle>
        <ModelDetail
          key={keyOf(model)}
          instanceId={target.instanceId}
          model={model}
          settings={previewSettings}
          section={section}
          onBack={onClose}
          backLabel={t("workbenchModelDetailClose")}
        />
      </DialogContent>
    </Dialog>
  );
}

type Note = { tone: "info" | "warning" | "error"; text: string; refresh?: boolean };

function SlotPicker({
  target,
  node,
  slot,
  models,
  loading,
  error,
  canRefresh,
}: {
  target: WorkbenchTarget;
  node: WorkbenchNode;
  slot: ModelSlot;
  models: ModelFile[];
  loading: boolean;
  error: string;
  canRefresh: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { openImagePreview } = useImagePreview();
  const [query, setQuery] = React.useState("");
  const [family, setFamily] = React.useState("");
  //: 没填成的那一句(不在下拉里、桥没做成):**只在回话到了时换**,填的过程中不先撤掉 —— 撤掉再放回来,下面整个列表会先
  //: 往上跳、再往下跳(维护者:「每次切换模型都会导致右侧这个窗口闪烁一下」)。填成了不另说一句(维护者不要):选中的那一行
  //: 换过去就是回答;上一次没填成的那句随之撤掉
  const [note, setNote] = React.useState<Note | null>(null);
  //: 说有预览图、取的时候却没取到的那几个:缩略图换成了占位,也就没有大图可看
  const [failed, setFailed] = React.useState<ReadonlySet<string>>(() => new Set());
  //: 预览图分档、NSFW 单独管:和模型库是同一份设置(记在本机),这里也能改
  const [previewSettings] = useModelPreviewSettings();
  const treatmentOf = (model: ModelFile) => previewTreatment(previewSettings, Boolean(model.nsfw?.flagged));
  const families = folderFamilies(models, slot.folder);
  //: 选文本编码器的格子:合节点现在 type 的排前面(不合的在最后、标出来)
  const listed = byRecipe(folderModels(models, slot.folder, { query, family }), slot.recipe);
  const present = presentIn(models, slot.folder, slot.value);

  const pick = useMutation({
    mutationFn: (model: ModelFile) =>
      workbenchCall({ op: "setWidget", node: node.id, widget: slot.widget, value: model.name }),
    onSuccess: (result) => {
      if (result.ok) setNote(null);
      else if (result.error === "notInList") setNote({ tone: "warning", text: t("workbenchModelsNotInList"), refresh: true });
      else setNote({ tone: "error", text: t("workbenchCallFailed").replace("{why}", "message" in result && result.message ? result.message : result.error) });
    },
  });
  const refresh = useMutation({
    mutationFn: () => workbenchCall({ op: "refreshCombos" }),
    onSuccess: (result) => {
      setNote(result.ok ? { tone: "info", text: t("workbenchCombosRefreshed") } : { tone: "error", text: t("workbenchCallFailed").replace("{why}", result.error) });
      void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
    },
  });

  const actions = React.useContext(ModelActionsContext);
  const openDetail = (model: ModelFile) => actions?.open(model);
  const previewable = (model: ModelFile) => model.has_preview && !failed.has(model.name);
  //: 看大图:这一页列着的、看得清的成组翻(按列表的顺序)。点的是模糊着、不显示的那一张时只开它 —— 点它是明确要看这一张,
  //: 翻到别的就等于没经同意替人把它们都看清了
  const preview = (model: ModelFile) => {
    const pick = previewPick(previewSettings);
    const item = (one: ModelFile) => ({
      src: modelPreviewUrl(target.instanceId, one.folder, one.name, pick),
      title: one.title || modelBaseName(one.name),
      ...(one.preview_kind === "video" ? { video: true } : {}),
    });
    const clear = (one: ModelFile) => previewable(one) && treatmentOf(one) === "clear";
    const gallery = clear(model) ? listed.slice(0, LISTED).filter(clear).map(item) : [item(model)];
    openImagePreview({ ...item(model), gallery });
  };

  return (
    <section aria-label={`${slot.widget} · ${slot.folder}`} className="grid gap-2.5">
      <header className="grid gap-1">
        <h3 className="m-0 flex min-w-0 items-center gap-1.5 text-ui-sm font-semibold text-foreground">
          <Truncate>{node.title || node.type}</Truncate>
          <span className="shrink-0 text-ui-xs font-normal text-muted-foreground">#{node.id} · {slot.widget}</span>
        </h3>
        {/* 固定一行的高:「这台 ComfyUI 上没有」那枚标签比字高,一出一没整块会跟着跳 */}
        <div className="flex h-6 min-w-0 items-center gap-1.5 text-ui-xs text-muted-foreground">
          <span className="shrink-0">{t("workbenchModelsCurrent")}</span>
          <Truncate className="min-w-0 text-foreground">{slot.value || "—"}</Truncate>
          {!loading && !error && !present && <CatalogBadge tone="warning">{t("workbenchModelsMissing")}</CatalogBadge>}
        </div>
      </header>
      {note && (
        <PanelNote
          tone={note.tone}
          action={note.refresh && canRefresh ? (
            <Button variant="outline" size="xs" className="shrink-0" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              <RefreshCcw size={12} />
              {t("workbenchCombosRefresh")}
            </Button>
          ) : undefined}
        >
          {note.text}
        </PanelNote>
      )}
      {!loading && !error && !present && (
        <ModelDownload target={target} folder={slot.folder} wanted={slot.value}
                       doneLabel={t(canRefresh ? "workbenchDownloadDone" : "workbenchDownloadDoneManual")}
                       onDone={() => {
                         void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
                         if (canRefresh) refresh.mutate();
                       }} />
      )}
      <div className="flex items-center gap-1.5">
        <SearchInput className="min-w-0 flex-1" size="xs" value={query} placeholder={t("workbenchModelsSearch").replace("{folder}", slot.folder)}
                 aria-label={t("workbenchModelsSearch").replace("{folder}", slot.folder)} onChange={(event) => setQuery(event.target.value)} />
        <ModelPreviewSettingsButton compact />
      </div>
      {families.length > 1 && (
        <div role="group" aria-label={t("workbenchModelsFamily")} className="flex flex-wrap gap-1">
          {["", ...families].map((one) => (
            <button
              key={one || "all"}
              type="button"
              aria-pressed={family === one}
              className={cn(
                "h-6 cursor-pointer rounded-full border px-2 text-ui-xs",
                family === one ? "border-primary/50 bg-accent text-primary" : "border-border bg-transparent text-muted-foreground hover:bg-secondary",
              )}
              onClick={() => setFamily(one)}
            >
              {one || t("workbenchModelsFamilyAll")}
            </button>
          ))}
        </div>
      )}
      {loading ? (
        <LoadingState label={t("workbenchModelsLoading")} className="h-auto py-6" />
      ) : error ? (
        <PanelNote tone="error">{error}</PanelNote>
      ) : listed.length === 0 ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workbenchModelsEmpty")}</p>
      ) : (
        <ul
          aria-label={t("workbenchModelsList").replace("{folder}", slot.folder)}
          className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-3 p-0"
        >
          {/* 卡片网格:列数由容器宽度自己决定(auto-fill + minmax),不写死断点 —— 这一列会被拖宽拖窄。
              下限 10rem(160px):内容宽 328px 起两列、496px 起三列;间距 12px 给卡片留呼吸。 */}
          {listed.slice(0, LISTED).map((model) => {
            const chosen = model.name.replace(/\\/g, "/") === slot.value.replace(/\\/g, "/");
            const filling = pick.isPending && pick.variables?.name === model.name;
            const name = model.title || modelBaseName(model.name);
            //: 第二行:前几个触发词;没有就说上面没说的 —— 有标题时是文件名,没标题(上面已经是文件名)时是子目录,都没有就不写
            const subtitle = (model.triggers ?? []).slice(0, 3).join(", ")
              || (model.title ? modelBaseName(model.name) : modelSubFolder(model.name));
            const thumb = (
              <ModelThumb compact instanceId={target.instanceId} model={model} treatment={treatmentOf(model)}
                          onFailed={() => setFailed((current) => new Set([...current, model.name]))} />
            );
            return (
              <ModelContextMenu key={model.name} model={model} openLabel={t("workbenchModelDetail")}>
                {() => (
                  <li
                    data-model-row=""
                    className={cn(
                      "group/thumb relative min-w-0 rounded-lg border",
                      chosen ? "border-primary/50 bg-accent" : "border-transparent hover:bg-secondary",
                    )}
                  >
                    {/* 整张卡是一颗按钮:点哪儿(缩略图那层除外)都是填进这一格。缩略图在里面,所以填的过程中那颗转圈
                        也在按钮里 —— 不只是变灰(见 design/pendingButtons)。竖排 grid:图一格、名字与 meta 一格 */}
                    <button
                      type="button"
                      aria-pressed={chosen}
                      aria-busy={filling || undefined}
                      disabled={pick.isPending}
                      className="grid w-full cursor-pointer gap-2 rounded-lg border-0 bg-transparent p-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-default"
                      onClick={() => pick.mutate(model)}
                    >
                      {/* 固定 4:3 且填满卡宽:图片 object-cover,卡片高矮不跟着原图比例变 */}
                      <span className="relative block aspect-[4/3] w-full overflow-hidden rounded-md bg-secondary">
                        <span className="absolute inset-0 block [&>*]:size-full">{thumb}</span>
                        {/* 填的过程中是转圈,填好了是对勾(尺寸不变)。压在缩略图的右下角;和右上角的 ⓘ 分处两头,
                            永不重叠。只是画给人看的状态,读屏听按钮的 aria-pressed / aria-busy,自己不接点击 */}
                        {(filling || chosen) && (
                          <span
                            data-model-state=""
                            aria-hidden
                            className="pointer-events-none absolute bottom-1 right-1 z-10 grid size-4 place-items-center"
                          >
                            {filling ? <Loader2 size={14} className="animate-mosael-spin text-muted-foreground" />
                              : <Check size={14} className="text-primary" />}
                          </span>
                        )}
                      </span>
                      <span className="grid min-w-0 gap-0.5">
                        {/* 名字的说明显式朝下:这一列是「左」的 Hint 区域(见 ComfyWorkbench 的 COLUMN_REGION),跟着区域走会横到
                            左边的画布上(维护者)。卡片下方有地方,往下弹不盖住这张卡 */}
                        <Truncate side="bottom" className="text-ui-xs font-medium text-foreground">{name}</Truncate>
                        {/* meta 行:底模徽标、文本编码器、副题,最后是 NSFW 与预览来源这一对;没有 hint 只有角标的卡也要画。
                            所有徽标同一档高度(和 CatalogBadge 一样);角标排在最后(维护者:NSFW 标应该在最后),
                            Hint 跟着徽标,名字与它们上下,不在卡尾另起一列 */}
                        {(model.nsfw?.flagged || (model.preview_origin && model.preview_origin !== "server") || model.encoder?.label || model.family || subtitle) && (
                          <span className="flex min-w-0 flex-wrap items-center gap-1 text-ui-2xs text-muted-foreground">
                            {(model.encoder?.label || model.family) && <CatalogBadge tone="muted">{model.encoder?.label || model.family}</CatalogBadge>}
                            <EncoderRecipeMark model={model} recipe={slot.recipe} />
                            {subtitle && <Truncate side="bottom">{subtitle}</Truncate>}
                            <NsfwMark nsfw={model.nsfw} className="h-6" />
                            <PreviewOriginMark origin={model.preview_origin} className="h-6 shadow-none" />
                          </span>
                        )}
                      </span>
                    </button>
                    {/* 看大图:缩略图上那一层。透明的一颗按钮,盖住缩略图;位置和里面那张图同一块
                        (卡内边距 p-2,所以 left/right/top 也是 2、比例同样是 4:3) */}
                    {previewable(model) && (
                      <IconButton
                        unstyled
                        data-model-preview=""
                        label={t("workbenchModelsPreview").replace("{name}", name)}
                        className="absolute left-2 right-2 top-2 aspect-[4/3] cursor-zoom-in rounded-md border-0 bg-transparent p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                        onClick={() => preview(model)}
                      />
                    )}
                    {/* 查看详情:常在卡片里(不靠悬停才出现),压在缩略图右上角;点卡本身照旧是填进画布。
                        和右下角的 ✓ 分处两头,永不重叠 */}
                    <IconButton
                      unstyled
                      data-model-detail={keyOf(model)}
                      label={t("workbenchModelDetailOpen").replace("{name}", name)}
                      className={cn(
                        "absolute right-2 top-2 z-10 grid size-7 cursor-pointer place-items-center rounded-md border-0 bg-transparent p-0",
                        "text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        // 常显(维护者:卡片形态下不需要悬停显示,安排在卡里就行)。压在图上,给一层底才看得清
                        "bg-background/60 backdrop-blur-xs",
                      )}
                      onClick={() => openDetail(model)}
                    >
                      <Info size={14} />
                    </IconButton>
                  </li>
                )}
              </ModelContextMenu>
            );
          })}
          {listed.length > LISTED && (
            <li className="col-span-full px-2 text-ui-xs text-muted-foreground">
              {t("workbenchModelsMore").replace("{n}", String(listed.length - LISTED))}
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
