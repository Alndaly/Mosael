import { CollectionDetail, COLLECTION_DETAIL_PAGE, COLLECTION_DETAIL_HEADING, DETAIL_INDEX_ITEM, DETAIL_INDEX_SELECTED, DETAIL_INDEX_TEXT } from "@/components/layout/CollectionDetail";
import { assetKeys } from "@/api/queryKeys";
import { PageHeading } from "@/components/layout/StudioPage";
import React from "react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/textarea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, ChevronsDownUp, ChevronsUpDown, CircleAlert, CircleArrowUp, Copy, KeyRound, Lock, Play, Plug, Plus, RefreshCcw, Store, Trash2 } from "lucide-react";

import {
  clearPluginInvocations,
  createPluginInstance,
  invokePluginTool,
  listPluginCredentials,
  listPluginInvocations,
  listPluginMarket,
  listPluginPackages,
  listPluginPermissions,
  pluginDir,
  refreshPluginInstance,
  removePluginInvocation,
  rescanPlugins,
  savePluginCredentials,
  setPluginCapabilities,
  setPluginPermissions,
  updatePluginInstance,
  type PluginField,
  type PluginInstanceCreate,
  type LocalService,
  type PluginInstance,
  type PluginInvocation,
  type PluginPackage,
} from "@/api/client";
import { splitErrorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { OPEN_MARKET_FOR_CAPABILITY, OPEN_PLUGIN_IN_MARKET, useOpenRequest } from "@/lib/deepLink";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { Switch } from "@/components/ui/switch";
import { EmptyState, PageLoadError } from "@/components/layout/EmptyState";
import { PluginMarketDialog } from "@/features/plugins/PluginMarket";
import { DocsButton, HintedFact, MoreActions, PluginHero, PluginOverview, docsOf, profileOfPackage, type PluginStatus } from "@/features/plugins/PluginProfile";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDraftText } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Skeleton } from "@/components/ui/skeleton";
import { SettingsBlock, SettingsRow } from "@/components/settings/settings-layout";
import { usePersistentSelection } from "@/lib/usePersistentTab";
import { FIELD_TRIGGER_CHEVRON, fieldTriggerClass } from "@/components/ui/field-trigger";
import { formatInvocationResult } from "@/features/plugins/invocationResult";
import { CodeConfigControl, CodeFieldEditor, isCodeField, jsonProblem } from "@/features/plugins/CodeConfigField";
import { GenerationModelsRow } from "@/features/plugins/ProvidedModels";
import { Disclosure } from "@/components/ui/disclosure";
import { DeleteConnectionDialog, UninstallPluginDialog } from "@/features/plugins/LocalServiceRemoval";
import { ConnectionLibraries } from "@/features/plugins/ConnectionLibraries";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { Hint } from "@/components/ui/tooltip";
import { useConnectionOpen } from "@/features/plugins/connectionOpen";
import type { MessageKey } from "@/app/messages";
import { ToolEffectBadge } from "@/features/plugins/ToolEffectBadge";
import { ConnectionAuthorization } from "@/features/plugins/ConnectionAuthorization";
import { ConnectionPermissionNotice, waitingForPermissions } from "@/features/plugins/ConnectionPermissions";
import { ConnectionNetwork } from "@/features/plugins/ConnectionNetwork";
import {
  ConnectionLocalService,
  LocalServiceDiscovery,
  SERVICE_ADDRESS_FIELD,
  WhereChoice,
  detectNewDirectory,
  useRefreshWhenRunning,
  type Where,
} from "@/features/plugins/ConnectionLocalService";
import { machineKey, serviceIssue, useLocalService } from "@/features/plugins/localServiceStatus";
import { describePermission } from "@/features/plugins/pluginPermissions";
import { PathField } from "@/components/settings/PathField";
import { useIsDeploymentAdmin } from "@/app/auth";
import { ConnectionPackageSources } from "@/features/plugins/ConnectionPackageSources";
import { GroupActions } from "@/features/plugins/GroupActions";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";
import { ToolRowFrame } from "@/features/plugins/ToolRowFrame";
import { useCapabilityTerms } from "@/features/plugins/capabilityTerms";
import { CapabilityUseList, type CapabilityUse } from "@/components/settings/CapabilityUseList";
import { entryOrigin, formedGroups, type EntryGroup } from "@/lib/entryNames";
import { cn } from "@/lib/utils";
import { NodeConfigForm, nodeConfigTiers, useNodeFieldOptions, type ConfigSpec } from "@/features/nodeForms/NodeConfigForm";

/**
 * 插件页 = 包 → 连接 → 能力 三层。
 *
 * 左边列的是**包**(磁盘上装了什么),右边是这个包的**连接**(一次具体接入:配置 + 凭据 +
 * 启用 + 勾了哪些工具)。一个包可以有多个连接 —— TikHub 一个包对应十几个平台端点,
 * B站一个、抖音一个,各有各的凭据和名字。
 *
 * 设计与取舍见 docs/PLUGIN_ARCHITECTURE.md。
 */
export function PluginsView({ workspaceId }: { workspaceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();

  const packages = useQuery({ queryKey: ["plugins"], queryFn: () => listPluginPackages() });
  // 插件目录由后端算、后端报:Windows 上它不是 `~/.mosael/`,文案里写死找不到地方。
  const pluginsDir = useQuery({
    queryKey: ["plugins-dir"],
    queryFn: () => pluginDir(),
    staleTime: Infinity,
  });
  const scan = useMutation({
    //: 带上扫之前已经登记的那几个,扫完说出多了哪几个 —— 此前转一下就结束,扫没扫到东西看不出来(体检 UM-32)。
    mutationFn: (known: ReadonlySet<string>) => rescanPlugins().then((after) => after.filter((pkg) => !known.has(pkg.id))),
    onSuccess: (added) =>
      toast.success(
        added.length > 0
          ? t("pluginScanAdded").replace("{n}", String(added.length)).replace("{names}", added.map((pkg) => pkg.name).join(t("listSeparator")))
          : t("pluginScanNothingNew"),
      ),
    // 失败时也刷新:扫描跳过坏掉的那个包、照样登记别的(后端说清是哪个),列表得跟上登记上的那些。
    onSettled: () => invalidatePluginDependents(qc),
  });
  //: 列表上标出哪几个有新版(和详情页头、插件市场同一份索引、同一个 query key):此前只有点进详情才看得到(体检 UM-32)。
  const market = useQuery({ queryKey: ["plugin-market"], queryFn: () => listPluginMarket(), retry: false });
  const updatable = new Set((market.data?.plugins ?? []).filter((entry) => entry.update_available).map((entry) => entry.id));

  const list = packages.data ?? [];
  // 选中的那一个**活过导航** —— 切走再回来还停在他刚才看的那条(见 lib/usePersistentTab)。
  // 它被删掉时自动回落到列表第一条,那正是下面这行本来就在做的事。
  const [selectedId, setSelectedId] = usePersistentSelection(
    "plugins",
    packages.data?.map((item) => item.id),
  );
  //: 市场是**去找新东西**,和「管理已经装了的」不是一件事。挤成同一栏的两个页签时,它得
  //: 挤在那条几百像素宽的侧栏里 —— 一个用来浏览的列表被塞进了一个用来选中的列表的位置。
  //: 现在它是头部的一个按钮 + 一张弹窗,宽度归它自己。
  const [marketOpen, setMarketOpen] = React.useState(false);
  const [marketFocus, setMarketFocus] = React.useState<string | null>(null);
  //: 从设置「能力提供方」来:打开市场,只看能做这件事的插件。
  const [marketCapability, setMarketCapability] = React.useState<string | null>(null);
  useOpenRequest(OPEN_MARKET_FOR_CAPABILITY, (capability) => {
    setMarketCapability(capability);
    setMarketOpen(true);
  });
  //: 官网「在 Mosael 中打开」:装过了就选中它的页,没装就打开市场、找到它 —— 装不装由人点。
  useOpenRequest(
    OPEN_PLUGIN_IN_MARKET,
    (pluginId) => {
      if (!packages.isSuccess) return false;
      if (packages.data.some((item) => item.id === pluginId)) {
        setSelectedId(pluginId);
      } else {
        setMarketFocus(pluginId);
        setMarketOpen(true);
      }
    },
    [packages.isSuccess],
  );
  const empty = packages.isSuccess && list.length === 0;
  const selected = list.find((item) => item.id === selectedId) ?? list[0] ?? null;
  const openInMarket = (pluginId: string) => {
    setMarketFocus(pluginId);
    setMarketOpen(true);
  };
  const marketDialog = (
    <PluginMarketDialog
      open={marketOpen}
      focusId={marketFocus}
      capability={marketCapability}
      onOpenChange={(next) => {
        setMarketOpen(next);
        if (!next) {
          setMarketFocus(null);
          setMarketCapability(null);
        }
      }}
      onChanged={() => invalidatePluginDependents(qc)}
      //: 市场里装着的那一个点「管理」:关掉市场,在这一页选中它 —— 新建连接、设置连接都在这儿。
      onManage={(pluginId) => {
        setMarketOpen(false);
        setMarketFocus(null);
        setMarketCapability(null);
        setSelectedId(pluginId);
      }}
    />
  );


  const heading = <PageHeading className={COLLECTION_DETAIL_HEADING} title={t("pluginsTitle")} description={t("studioPluginsDesc")} count={packages.data?.length} actions={<><ScanButton pending={scan.isPending} onScan={() => scan.mutate(new Set((packages.data ?? []).map((pkg) => pkg.id)))} /><Button onClick={() => setMarketOpen(true)}><Store />{t("studioBrowsePlugins")}</Button></>} />;
  if (empty) return <div className={COLLECTION_DETAIL_PAGE}>
    {heading}<div className="flex min-h-0 flex-1 overflow-y-auto"><EmptyState icon={<Plug size={28} />} title={t("pluginsTitle")} body={t("noPluginsGuide").replace("{dir}", pluginsDir.data?.path ?? "")} action={<Button onClick={() => setMarketOpen(true)}><Store />{t("studioBrowsePlugins")}</Button>} /></div>
    {marketDialog}
  </div>;

  return (
    <div className={COLLECTION_DETAIL_PAGE}>
      {heading}
      <CollectionDetail storageKey="plugins" label={t("pluginsTitle")} selected={!!selected} index={<>
            {packages.isLoading &&
              list.length === 0 &&
              [0, 1, 2].map((i) => (
                <div key={`sk${i}`} className="flex items-center gap-[9px] px-2 py-1.5" aria-hidden>
                  <div className="grid min-w-0 flex-1 gap-1.5">
                    <Skeleton className="h-3.5 w-3/4 rounded" />
                    <Skeleton className="h-2.5 w-1/3 rounded" />
                  </div>
                </div>
              ))}
            {list.map((item) => {
              //: 绿点说的是「在用」:启用了**而且**能用。启用着但缺凭据、没授权的,亮绿点就是在说谎。
              const live = (item.instances ?? []).filter((i) => i.enabled && !i.blocked_reason).length;
              //: 启用着、却因为缺权限停了(插件更新后多要了几项):不亮绿点,标黄、说「待授权」,不让人以为它坏了。
              const waiting = waitingForPermissions(item.instances ?? []);
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cn(DETAIL_INDEX_ITEM, selected?.id === item.id && DETAIL_INDEX_SELECTED)}
                  aria-current={selected?.id === item.id ? "true" : undefined}
                  onClick={() => setSelectedId(item.id)}
                >
                  <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", live > 0 && "bg-success", waiting && "bg-warning")} />
                  <span className={DETAIL_INDEX_TEXT}>
                    <strong>{item.name}</strong>
                    <small>
                      v{item.version} · {t("pluginConnectionCount").replace("{n}", String((item.instances ?? []).length))}
                      {waiting && <span className="text-warning"> · {t("pluginPermWaiting")}</span>}
                      {updatable.has(item.id) && <span data-plugin-updatable="" className="text-warning"> · {t("pluginMarketHasUpdate")}</span>}
                    </small>
                  </span>
                </button>
              );
            })}
            {packages.isError && list.length === 0 && (
              <PageLoadError size="compact" icon={<Plug size={15} />} error={packages.error} onRetry={() => void packages.refetch()} />
            )}
            {packages.isSuccess && list.length === 0 && (
              <p className="m-0 px-2 py-3 text-ui-xs leading-[1.6] text-muted-foreground">
                {t("noPluginsGuide").replace("{dir}", pluginsDir.data?.path ?? "")}
              </p>
            )}
      </>}>
          {selected ? (
            <PackageDetail key={selected.id} pkg={selected} workspaceId={workspaceId} onUpdate={() => openInMarket(selected.id)} />
          ) : (
            <EmptyState icon={<Plug size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
      </CollectionDetail>
      {marketDialog}
    </div>
  );
}

/** 扫描按钮:pending 时图标转起来、文案改成「扫描中」—— 以前只是 disabled,点下去像没点上。 */
function ScanButton({ pending, onScan }: { pending: boolean; onScan: () => void }) {
  const t = useI18n();
  return <Button variant="outline" loading={pending} onClick={onScan}>
    <RefreshCcw />{pending ? t("scanningPlugins") : t("scanPlugins")}
  </Button>;
}

//: 导出**只为测试**:连接的展开 / 收起、「全部收起」由测试盯着(见 ConnectionCollapse.dom.test)。
/**
 * 插件页右边:一个装好的插件。
 *
 * **页头和市场详情是同一个**(PluginProfile 的 PluginHero):图标、名字、状态、一句话、版本和作者,右边是这一页
 * 能做的事 —— 新建连接(还没有连接时是主按钮)、有新版时「更新」(打开市场里它那一页)、文档、⋯ 里的卸载。
 * 此前名字下面那行「v0.7.3 · 作者 Mosael」和一排同样灰的文字按钮挤在一起,读不出哪个能点;插件 ID、运行方式
 * 又单占一行小字。
 *
 * 下面两页:**连接**(这一页的主体,默认停在这儿)和**关于**(和市场详情同一份概览:能做什么、介绍、工具、
 * 权限、插件 ID 这些)。连接多、展开后很长,关于是查的时候才看的 —— 摞在同一页里谁都往下挤谁。
 */
export function PackageDetail({
  pkg,
  workspaceId,
  onUpdate,
}: {
  pkg: PluginPackage;
  workspaceId: string;
  /** 有新版时页头的「更新」:打开市场里它那一页(装之前的确认在那儿)。不给就不画。 */
  onUpdate?: () => void;
}) {
  const t = useI18n();
  const market = useQuery({ queryKey: ["plugin-market"], queryFn: () => listPluginMarket(), retry: false });
  const listed = market.data?.plugins.find((entry) => entry.id === pkg.id);
  //: 装着的那一版清单里没写 docs(写 docs 之前发的版本)时,用市场索引里同一个插件的那一页 —— 文档说的是这个插件,不是这一版。
  const profile = profileOfPackage(pkg, pkg.docs || listed?.docs || "");
  const docs = docsOf(profile);
  const status: PluginStatus = pkg.bundled ? "bundled" : listed?.update_available ? "update" : "installed";
  const qc = useQueryClient();
  const [confirmUninstall, setConfirmUninstall] = React.useState(false);
  const [addOpen, setAddOpen] = React.useState(false);
  const [tab, setTab] = React.useState<"connections" | "about">("connections");

  const instances = pkg.instances ?? [];
  const instanceIds = React.useMemo(() => instances.map((one) => one.id), [instances]);
  //: 每个连接展开还是收起,按连接记在本机(见 connectionOpen):一个连接默认展开,几个默认收起,刚建的展开。
  const opened = useConnectionOpen(instanceIds);
  //: 刚建的那个:列表重读回来、它的卡片出现时滚到它 —— 几个连接时它排在最下面,不滚就看不到认目录的结果 / 安装计划。
  const arriving = React.useRef<string | null>(null);
  React.useEffect(() => {
    const id = arriving.current;
    if (!id || !instanceIds.includes(id)) return;
    arriving.current = null;
    const frame = window.requestAnimationFrame(() =>
      document.querySelector(`[data-connection="${id}"]`)?.scrollIntoView({ block: "start" }),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [instanceIds]);

  const canAdd = pkg.multiple || instances.length === 0;

  return (
    <div className="grid w-full min-w-0 content-start gap-5">
      {/* 卸载会删掉磁盘上的插件目录 —— 不可撤销,所以走确认;连接还留着本机服务的安装目录时一起问(ADR 0041 §4)。 */}
      <UninstallPluginDialog
        packageId={pkg.id}
        name={pkg.name}
        open={confirmUninstall}
        onCancel={() => setConfirmUninstall(false)}
        onDone={() => {
          setConfirmUninstall(false);
          invalidatePluginDependents(qc);
        }}
      />

      {/* **页头,不是卡片。** 包是这一页的身份 —— 它此前和连接一样是个 SettingsGroup,
          于是「TikHub」在屏幕上出现两次、长得一模一样,读的人分不清哪个是包哪个是连接。 */}
      <PluginHero
        profile={profile}
        status={status}
        headingLevel={2}
        facts={[
          status === "update" && listed ? (
            <span key="latest" className="tabular-nums">{t("pluginLatestVersion").replace("{v}", listed.version)}</span>
          ) : null,
          status === "bundled" ? (
            <HintedFact key="bundled" hint={t("pluginBundledHint")}>{t("pluginBundledFact")}</HintedFact>
          ) : null,
        ]}
        actions={
          <>
            {status === "update" && onUpdate && (
              <Button onClick={onUpdate}>
                <CircleArrowUp />
                {t("pluginUpdate")}
              </Button>
            )}
            {/* 「新建连接」排在最前:它是这一页最常做的事;一个连接都没有时它就是主按钮。 */}
            {canAdd && (
              <Button variant={instances.length === 0 && status !== "update" ? "default" : "outline"} onClick={() => setAddOpen(true)}>
                <Plus />
                {t("pluginNewConnection")}
              </Button>
            )}
            {/* 「文档」指向**这个插件在 Mosael 里怎么用**的那一页(已按语言挑好):连接是什么、凭据填哪儿、
                工具各干什么。两边都没有就退到它的主页;再没有就不画。 */}
            {docs && <DocsButton href={docs} />}
            {/* 随应用发的插件卸不掉(后端也拒):下次启动对账又会装回来,「删了又回来」比「删不了」更让人困惑。
                不想用就停用它的连接。卸载收在 ⋯ 里 —— 破坏性动作不和常用动作贴在一起。 */}
            {!pkg.bundled && (
              <MoreActions
                actions={[{ label: t("pluginUninstall"), icon: <Trash2 />, destructive: true, onSelect: () => setConfirmUninstall(true) }]}
              />
            )}
          </>
        }
      />

      <Tabs value={tab} onValueChange={(next) => setTab(next as "connections" | "about")} className="grid min-w-0 gap-5">
        <div className="flex min-w-0 items-end justify-between gap-3 border-b border-divider">
          <TabsList aria-label={t("pluginTabsLabel")} className="border-b-0">
            <TabsTrigger value="connections" className="gap-1.5">
              {t("pluginTabConnections")}{" "}
              <span className="text-ui-xs font-normal tabular-nums text-muted-foreground">{instances.length}</span>
            </TabsTrigger>
            <TabsTrigger value="about">{t("pluginTabAbout")}</TabsTrigger>
          </TabsList>
          {/* 连接多于一个时:一键全部收起 / 展开(有一个开着就是「全部收起」)。只作用于连接,所以只在那一页。 */}
          {tab === "connections" && instances.length > 1 && (
            <Button variant="ghost" size="sm" className="mb-1.5 text-muted-foreground" onClick={() => opened.setAll(!opened.anyOpen)}>
              {opened.anyOpen ? <ChevronsDownUp /> : <ChevronsUpDown />}
              {opened.anyOpen ? t("pluginCollapseAll") : t("pluginExpandAll")}
            </Button>
          )}
        </div>

        {/* 连接是这一页的**主体**。有几个就是几个;一个都没有时空状态在中间、带「新建」—— 页面空着时
            人的视线落在中央,页头那颗容易整个错过。重复的是按钮,不是说明文字。 */}
        <TabsContent value="connections" className="mt-0 grid min-w-0 content-start gap-4">
          {(pkg.services ?? []).length > 0 && (
            <LocalServiceDiscovery
              pkg={pkg}
              onConnected={(id) => {
                setTab("connections");
                opened.setOpen(id, true);
                arriving.current = id;
              }}
            />
          )}
          {instances.map((instance) => (
            <ConnectionCard
              key={instance.id}
              pkg={pkg}
              instance={instance}
              workspaceId={workspaceId}
              open={opened.isOpen(instance.id)}
              onOpenChange={(next) => opened.setOpen(instance.id, next)}
            />
          ))}
          {instances.length === 0 ? (
            <EmptyState
              size="compact"
              icon={<Plug size={15} />}
              title={t("pluginNoConnections")}
              body={t("pluginNoConnectionsBody")}
              action={
                canAdd ? (
                  <Button size="sm" onClick={() => setAddOpen(true)}>
                    <Plus size={13} /> {t("pluginAddConnection")}
                  </Button>
                ) : undefined
              }
            />
          ) : null}
        </TabsContent>
        <TabsContent value="about" className="mt-0 min-w-0">
          <PluginOverview profile={profile} />
        </TabsContent>
      </Tabs>

      {canAdd && (
        <NewConnectionDialog
          pkg={pkg}
          open={addOpen}
          onOpenChange={setAddOpen}
          onCreated={(id) => {
            // 新连接出现在「连接」页、展开着:本机的两种,卡片上就是认目录的结果 / 安装计划
            setTab("connections");
            opened.setOpen(id, true);
            arriving.current = id;
          }}
        />
      )}
    </div>
  );
}

/**
 * 新建一个连接。**弹窗而不是常驻表单** —— 建连接是低频操作,而它此前一直占着连接列表下方
 * 的版面;一个连接都没有时,它的说明还和空状态几乎逐字重复。
 *
 * 每个字段自带标签与说明。此前三个控件并排、只显示值:`127.0.0.1` 和 `9876` 还能猜出是主机
 * 和端口,而 Blender 插件那个「已关闭」(其实是"关闭上游遥测")完全猜不出来 —— 标签一直在
 * 清单里,只是被塞进了 placeholder,而 placeholder 只在空着时显示。
 *
 * **声明了本机服务的插件**(清单的 `services`,ADR 0041)一开始就选「在哪跑」,和连接页上的本机服务卡同一套:
 * - 连一台服务器:和没有本机服务的插件一样,只填配置;
 * - 用我自己装的:选目录、可选的解释器;服务器地址那一格不摆(端口由宿主分、写进去)。新建之前确认一次「会在这台机器上运行
 *   这个目录里的代码」,建好马上认一遍,结果摆在新连接的卡片上 —— 不再问第二次;
 * - 让 Mosael 装:没有路径(装在宿主分的目录里)。建好的连接展开就是安装计划,看过再点「开始安装」—— 这里不替人开始装。
 *
 * 本机的两种:连接、本机服务那一行、端口、地址在后端一个事务里建好;插件声明的权限列在弹窗里、建好时一起授予(建好马上要
 * 靠插件认目录、看安装计划,没授予它什么都不做);要部署管理员,别人那两颗是灰的、说为什么。别的配置项三种都有,
 * 凭据照旧填在建好的连接上。
 */
export function NewConnectionDialog({
  pkg, open, onOpenChange, onCreated,
}: {
  pkg: PluginPackage;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 建好了(弹窗已经关上,下次打开是一张新的):页面去展开这个新连接。 */
  onCreated: (instanceId: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const declared = (pkg.services ?? [])[0];
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const [where, setWhere] = React.useState<Where>("server");
  const [directory, setDirectory] = React.useState("");
  const [python, setPython] = React.useState("");
  const [confirming, setConfirming] = React.useState(false);
  //: 建好了:**下一次打开**是一张新的。不在建好的那一刻清 —— 关窗的淡出里表单会跳回缺省、确认框里的目录变成空的。
  const [used, setUsed] = React.useState(false);
  const [shownOpen, setShownOpen] = React.useState(open);
  if (open !== shownOpen) {
    setShownOpen(open);
    if (open && used) {
      setUsed(false);
      setDraft({});
      setWhere("server");
      setDirectory("");
      setPython("");
    }
  }
  const local = Boolean(declared) && where !== "server";
  //: 本机的两种,服务器地址那一格归宿主:不摆、不交
  const fields = (pkg.config_fields ?? []).filter((field) => !local || field.key !== SERVICE_ADDRESS_FIELD);
  const permissions = pkg.permissions ?? [];
  const create = useMutation({
    mutationFn: (body: Partial<PluginInstanceCreate>) => createPluginInstance(pkg.id, body),
    onSuccess: (created, body) => {
      const chosen = body.local_service;
      if (chosen?.mode === "directory") detectNewDirectory(qc, created.id, chosen.directory, chosen.python);
      invalidatePluginDependents(qc);
      // 建好就关窗、清草稿 —— 留着开会让人以为没成功,而新连接已经出现在下面的列表里了。
      onOpenChange(false);
      setUsed(true);
      onCreated(created.id);
    },
    //: 没建成:确认框收起,原因由全局的提示说(见 app/mutationErrors)
    onSettled: () => setConfirming(false),
  });
  const body = (): Partial<PluginInstanceCreate> => {
    if (!local) return { config: draft };
    const config = Object.fromEntries(Object.entries(draft).filter(([key]) => fields.some((field) => field.key === key)));
    const own = where === "directory";
    return {
      config,
      grant_permissions: permissions,
      local_service: {
        mode: own ? "directory" : "managed",
        directory: own ? directory.trim() : "",
        python: own ? python.trim() : "",
        confirm_run_code: own,
      },
    };
  };
  //: 有一段 JSON 填错了就不让建 —— 后端也会拒,但那时用户已经点完了,只拿回一句报错。
  const broken = fields.some((field) => field.type === "json" && jsonProblem(draft[field.key] ?? field.default ?? "") !== null);
  const ready = !broken && (!local || where !== "directory" || directory.trim().length > 0);
  // 没有配置项时还要分一次:有凭据的插件说"不需要配置"是错的 —— AppKey 这些确实要填,
  // 只是填在**建好之后的连接上**(凭据挂在连接上,不是插件上)。
  const hint = fields.length || local
    ? t("pluginNewConnectionDesc")
    : (pkg.credential_fields ?? []).length
      ? t("pluginNewConnectionCreds")
      : t("pluginNewConnectionSimple");
  const title = declared?.title ?? pkg.name;
  const machine = t(machineKey());
  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("pluginNewConnection")}
      // 配置项的说明常是两三行(地域、接入点的例子),420px 宽时一条说明折成五行,表单读起来像一列窄条。
      className={cn(fields.some(isCodeField) ? "w-[640px]" : "w-[520px]", "max-w-[calc(100vw-32px)]")}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={create.isPending} onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
          <Button
            loading={create.isPending && !confirming}
            disabled={!ready}
            onClick={() => (local && where === "directory" ? setConfirming(true) : create.mutate(body()))}
          >
            <Plus size={13} /> {t("pluginAddConnection")}
          </Button>
        </div>
      }
    >
      <div className="grid gap-4">
        <p className="m-0 text-ui-sm leading-[1.6] text-muted-foreground">{hint}</p>
        {declared && <NewConnectionWhere title={title} where={where} onChoose={setWhere} />}
        {local && where === "directory" && (
          <>
            <div className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{t("localServiceDirectory")}</span>
              <PathField
                kind="directory"
                label={t("localServiceDirectory")}
                placeholder={t("localServiceDirectoryPlaceholder")}
                value={directory}
                onChange={setDirectory}
                className="w-full"
              />
              <small className="text-ui-xs leading-[1.5] text-muted-foreground">{t("localServiceDirectoryDesc").replace("{title}", title)}</small>
            </div>
            <div className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{t("localServicePython")}</span>
              <PathField kind="file" label={t("localServicePython")} value={python} onChange={setPython} className="w-full" />
              <small className="text-ui-xs leading-[1.5] text-muted-foreground">{t("localServicePythonDesc")}</small>
            </div>
          </>
        )}
        {local && where === "managed" && (
          <div className="grid min-w-0 gap-1.5">
            <span className="text-ui-sm font-medium text-foreground">{t("localServicePlanWhere")}</span>
            <small className="text-ui-xs leading-[1.5] text-muted-foreground">{t("localServiceNewManagedDesc")}</small>
          </div>
        )}
        {local && (
          <div className="grid min-w-0 gap-1.5" data-new-connection-address>
            <span className="text-ui-sm font-medium text-foreground">{t("localServiceAddress")}</span>
            <small className="text-ui-xs leading-[1.5] text-muted-foreground">{t("localServiceAddressOnCreate")}</small>
          </div>
        )}
        {fields.map((field) => {
          // 代码字段不能包在 <label> 里:编辑器不是可被 label 关联的控件,而它的工具栏里有按钮 ——
          // label 会把点击转给它里面**第一个按钮**,于是点一下字段标题就等于点了「格式化」。
          const Row = isCodeField(field) ? "div" : "label";
          return (
            <Row key={field.key} className="grid min-w-0 gap-1.5">
              <span className="text-ui-sm font-medium text-foreground">{field.label}</span>
              {isCodeField(field) ? (
                <CodeFieldEditor
                  field={field}
                  value={draft[field.key] ?? field.default}
                  onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}
                  minHeight={120}
                  maxHeight={280}
                />
              ) : (
                <FieldInput
                  field={field}
                  value={draft[field.key] ?? field.default}
                  onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}
                />
              )}
              {/* 清单里的 help 此前一个字都没显示。Blender 插件那条正是用户会撞到的限制:
                  「互通要求 Blender 与后端在同一台电脑」。 */}
              {field.help && (
                <small className="text-ui-xs leading-[1.5] text-muted-foreground">
                  <InlineMarkdown text={field.help} />
                </small>
              )}
            </Row>
          );
        })}
        {local && permissions.length > 0 && (
          <div className="grid min-w-0 gap-1.5" data-new-connection-permissions>
            <span className="text-ui-sm font-medium text-foreground">
              {t("localServiceNewPermissions").replace("{n}", String(permissions.length))}
            </span>
            <ul className="m-0 grid list-none gap-1 p-0">
              {permissions.map((permission) => (
                <li key={permission} className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-ui-sm text-foreground">
                  <span>{describePermission(t, permission) ?? permission}</span>
                  <span className="timecode text-ui-xs text-muted-foreground">{permission}</span>
                </li>
              ))}
            </ul>
            <small className="text-ui-xs leading-[1.5] text-muted-foreground">{t("localServiceNewPermissionsDesc")}</small>
          </div>
        )}
      </div>
      {/* 用我自己装的:新建之前确认一次(和连接页上「检查并使用」同一句);建好之后认目录、起它都不再问 */}
      <ConfirmDialog
        open={confirming}
        title={t("localServiceConfirmTitle").replace("{where}", machine)}
        body={t("localServiceConfirmBody").replace("{directory}", directory.trim()).replace("{title}", title)}
        confirmLabel={t("localServiceConfirmRun")}
        pending={create.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => create.mutate(body())}
      />
    </ModalShell>
  );
}

/**
 * 新建弹窗里的「在哪跑」(插件声明了本机服务才有)。本机的两种要部署管理员(和连接页上的本机服务卡同一条规矩):别人那两颗是灰的,
 * 下面那句换成为什么 —— 「连一台服务器」照常能选。
 */
function NewConnectionWhere({ title, where, onChoose }: { title: string; where: Where; onChoose: (where: Where) => void }) {
  const t = useI18n();
  const admin = useIsDeploymentAdmin();
  return (
    <div className="grid min-w-0 gap-1.5" data-new-connection-where>
      <span className="text-ui-sm font-medium text-foreground">{t("localServiceWhere")}</span>
      <WhereChoice mode={where} localDisabledReason={admin ? undefined : t("localServiceAdminOnly")} onChoose={onChoose} />
      <small className="text-ui-xs leading-[1.5] text-muted-foreground">
        {admin ? t("localServiceWhereDesc").replace("{title}", title) : t("localServiceNewAdminOnly").replace("{where}", t(machineKey()))}
      </small>
    </div>
  );
}

/** 一个配置项 / 凭据项的控件。枚举给下拉、开关给 Switch,别的给文本框 —— 类型是声明出来的。
 *
 *  **只有一个选项的枚举不给下拉。** 那是插件作者钉死的值(Blender 插件的「关闭上游遥测」
 *  就是这样),渲染成下拉等于摆一个点开只有一项的控件 —— 看起来能操作、实际不能,比直接
 *  说明它是锁定的更让人困惑。 */
export function FieldInput({
  field,
  value,
  onChange,
  className,
  commit,
}: {
  field: PluginField;
  value: string;
  onChange: (value: string) => void;
  className?: string;
  /** 文本框什么时候往外交(见 useDraftText)。改的是服务端那份时给 `"blur"`:一段编辑一次请求。 */
  commit?: "change" | "blur";
}) {
  const t = useI18n();
  if (field.type === "enum") {
    const options = (field.options as { value: string; label: string }[]) ?? [];
    if (options.length <= 1) {
      const only = options[0];
      // **长得还是一个字段框。** 共用 fieldTriggerClass(),与旁边的下拉(默认档)逐像素一致 ——
      // 排成一列时,一行光秃秃的文字读起来像"这块没做完",那比"假下拉"更糟。
      // 变的只有两处:锁图标占了箭头的位置(说明它是钉死的),以及整块不可点。
      return (
        <div
          aria-readonly="true"
          className={cn(fieldTriggerClass(), "cursor-default text-muted-foreground", className)}
        >
          <Truncate>{only?.label ?? value}</Truncate>
          <Lock className={cn(FIELD_TRIGGER_CHEVRON, "size-3.5")} />
        </div>
      );
    }
    return (
      <SearchableSelect
        className={className}
        value={value}
        onValueChange={onChange}
        placeholder={t("pluginPickField").replace("{label}", field.label)}
        options={options.map((option) => ({ value: option.value, label: option.label }))}
      />
    );
  }
  if (field.type === "boolean") {
    //: 开关,不是一个写着 `false` 的文本框(用户截图:「不限制自定义代码」)。值照旧是字符串 —— 配置注入插件进程
    //: 时都是环境变量 —— 存 `"true"` / `"false"`,插件那头按字符串认。
    return (
      <Switch
        className={className}
        aria-label={field.label}
        checked={isTruthy(value)}
        onCheckedChange={(checked) => onChange(checked ? "true" : "false")}
      />
    );
  }
  return <FieldText field={field} value={value} onChange={onChange} className={className} commit={commit} />;
}

/** 配置里布尔值的字符串写法:`true` / `1` / `yes` / `on` 算开,别的(含空串 = 没填,按清单缺省的关)算关。 */
function isTruthy(value: string): boolean {
  return ["true", "1", "yes", "on"].includes(value.trim().toLowerCase());
}

/** 文本类的配置项。**草稿式**(见 components/ui/draft-text):连接上的配置住在服务端,
 *  直接 `value={服务端那份}` 的话每敲一个字发一次请求,回来之前框里的字还被写回旧值 —— 中文组词
 *  当场断掉,英文也会丢字。 */
function FieldText({ field, value, onChange, className, commit }: {
  field: PluginField; value: string; onChange: (value: string) => void; className?: string; commit?: "change" | "blur";
}) {
  if (field.multiline) {
    return <FieldTextarea field={field} value={value} onChange={onChange} className={className} commit={commit} />;
  }
  return <FieldLine field={field} value={value} onChange={onChange} className={className} commit={commit} />;
}

/** 多行的那种(一段 JSON 之类):单行框装一份几百行的东西,用户看到的只是它的第一行。 */
function FieldTextarea({ field, value, onChange, className, commit }: {
  field: PluginField; value: string; onChange: (value: string) => void; className?: string; commit?: "change" | "blur";
}) {
  const draft = useDraftText<HTMLTextAreaElement>({ value, onValueChange: onChange, commit });
  return <Textarea className={cn("min-h-28 w-[420px] max-w-full font-mono text-ui-xs", className)} placeholder={field.label} {...draft} />;
}

function FieldLine({ field, value, onChange, className, commit }: {
  field: PluginField; value: string; onChange: (value: string) => void; className?: string; commit?: "change" | "blur";
}) {
  const draft = useDraftText<HTMLInputElement>({ value, onValueChange: onChange, commit });
  return (
    <Input
      className={className}
      type={field.secret ? "password" : field.type === "number" ? "number" : "text"}
      placeholder={field.label}
      {...draft}
    />
  );
}

//: 导出**只为测试**:授权那一条摆在卡片的哪儿是结构,由测试盯着(见 PluginsView.dom.test)。
export function ConnectionCard({
  pkg,
  instance,
  workspaceId,
  open: openProp,
  onOpenChange,
}: {
  pkg: PluginPackage;
  instance: PluginInstance;
  workspaceId: string;
  /** 展开还是收起。不给就自己记(默认展开):单独渲染一张卡的地方(测试)不必管。 */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const [ownOpen, setOwnOpen] = React.useState(true);
  const open = openProp ?? ownOpen;
  const setOpen = (next: boolean) => (onOpenChange ? onOpenChange(next) : setOwnOpen(next));
  const bodyId = React.useId();
  const bodyRef = React.useRef<HTMLDivElement>(null);

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      updatePluginInstance(instance.id, body),
    onSuccess: () => invalidatePluginDependents(qc),
  });
  const refresh = useMutation({
    mutationFn: () => refreshPluginInstance(instance.id),
    // 失败也刷新:拉不到的原因记在连接上(capability_status.tools),卡片要跟着说出来。
    onSettled: () => invalidatePluginDependents(qc),
  });
  const setCapabilities = useMutation({
    mutationFn: (tools: Record<string, boolean>) =>
      setPluginCapabilities(instance.id, { tools }),
    onSuccess: () => invalidatePluginDependents(qc),
  });

  const grants = useQuery({
    queryKey: ["plugin-permissions", instance.id],
    queryFn: () => listPluginPermissions(instance.id),
    enabled: (pkg.permissions ?? []).length > 0,
  });
  const setGrant = useMutation({
    mutationFn: (grantsBody: Record<string, boolean>) =>
      setPluginPermissions(instance.id, { grants: grantsBody }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plugin-permissions", instance.id] });
      invalidatePluginDependents(qc);
    },
  });

  //: 声明了本机服务的插件(ADR 0041):连接页多一块「本机服务」。服务器地址那一格(SERVICE_ADDRESS_FIELD)归它摆 ——
  //: 「连一台服务器」时就是这一格;本机的两种一选上就换成卡片里只读的地址(端口由 Mosael 分,在「高级」里改)
  const services = pkg.services ?? [];
  const localService = useLocalService(instance.id, services.length > 0);
  useRefreshWhenRunning(localService.data?.state);
  const configFields = pkg.config_fields ?? [];
  const serviceAddressField = services.length > 0 ? configFields.find((field) => field.key === SERVICE_ADDRESS_FIELD) : undefined;
  const exposedCount = (instance.tools ?? []).filter((tool) => tool.exposed).length;
  const tools = instance.tools ?? [];
  //: 替宿主做生成的插件(ComfyUI 这类)把模型交给选择器,而不是把工具交给智能体 —— 它的
  //: 「刷新」刷的是模型清单,卡片上该说的是「几个模型」而不是「开放了 0 / 0 个工具」。
  const generates = (pkg.provides ?? []).includes("generation");
  //: 只替宿主做事、自己不报工具的插件(只认领目录类能力的那种):说它做什么、去哪用;显示「已开启 0 / 0 个工具」
  //: 「启用并授权后会显示可调用工具」只会让人以为它坏了。认领调用类能力的(MinerU)是普通工具,在工具表里(ADR 0033)。
  const hostCapabilities = (pkg.provides ?? []).filter((one) => one !== "generation");
  const { labelOf } = useCapabilityTerms();
  const hostOnly = !generates && tools.length === 0 && hostCapabilities.length > 0;
  //: 工具表为什么是空的。有 blocked_reason 就说它;没有时,MCP 连接是还没拿到清单(拉过但失败就带上原因),
  //: 下一步是「刷新工具」—— 说「启用并授权后会显示」会让一个已经启用、授权好的连接读起来像坏了。
  const noToolsText = ((): string => {
    if (instance.blocked_reason) return instance.blocked_reason;
    if (pkg.kind !== "mcp") return t("pluginNoToolsDeclared");
    const fetchError = instance.capability_status?.tools?.error;
    return fetchError ? t("pluginToolsFetchFailed").replace("{error}", fetchError) : t("pluginToolsNotFetched");
  })();

  //: 收起时那一行说的话:这个连接此刻怎么样(可用 / 已停用 / 要处理的原因)、开了几个工具或几个模型。
  const issue = connectionIssue(pkg, instance, localService.data);
  const summaryText = ((): string => {
    if (generates && tools.length === 0) {
      const models = instance.capability_status?.generation?.models;
      return typeof models === "number" ? t("pluginConnModels").replace("{n}", String(models)) : t("pluginGenerationDesc");
    }
    if (hostOnly) return t("pluginHostCapabilityDesc").replace("{list}", hostCapabilities.map(labelOf).join(t("listSeparator")));
    if (tools.length === 0) return instance.blocked_reason ? "" : noToolsText;
    return t("pluginExposedCount").replace("{n}", String(exposedCount)).replace("{total}", String(tools.length));
  })();
  const address = summaryAddress(pkg, instance);
  const title = !pkg.multiple && instance.name === pkg.name ? t("pluginConnectionSettings") : instance.name;

  //: 点开**这一个**连接时定位到出问题的那一项(授权那一条、缺的那一格配置、凭据……):要处理的事收起时标着,
  //: 点开就该直接看到它。「全部展开」不做:几个连接各抢一次焦点,页面会跳到最后那个出问题的。
  //: 模型库读不出来时的「去检查连接设置」也走这里:展开、定位到服务器地址那一格(清单的 summary_field)。
  const focusNext = React.useRef<string | null>(null);
  const [focusRequest, setFocusRequest] = React.useState(0);
  const settingsTarget = (() => {
    const fields = pkg.config_fields ?? [];
    const field = fields.find((one) => one.key === pkg.summary_field) ?? fields[0];
    return field ? `config:${field.key}` : null;
  })();
  const checkSettings = () => {
    focusNext.current = settingsTarget;
    setOpen(true);
    setFocusRequest((n) => n + 1);
  };
  React.useEffect(() => {
    const target = focusNext.current;
    if (!open || !target) return;
    focusNext.current = null;
    const frame = window.requestAnimationFrame(() => {
      const section = bodyRef.current?.querySelector<HTMLElement>(`[data-connection-section="${target}"]`);
      if (!section) return;
      section.scrollIntoView({ block: "center" });
      section.querySelector<HTMLElement>("button, input, textarea, [tabindex]:not([tabindex='-1'])")?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
    // 只在展开的那一刻(或被要求定位时)跑:展开着时改别的(刷新、保存)不该把焦点拽回去
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, focusRequest]);

  //: 清单声明的一格配置(一行):一段代码的只放摘要和「编辑」,别的就地改、离开时存。
  const configRow = (field: (typeof configFields)[number]) => (
    <div key={field.key} data-connection-section={`config:${field.key}`}>
      <SettingsRow label={field.label} description={field.help ? <InlineMarkdown text={field.help} /> : undefined}>
        {isCodeField(field) ? (
          /* 一段代码塞不进这一栏:这里只放摘要和「编辑」,编辑在大弹窗里(见 CodeConfigField)。 */
          <CodeConfigControl
            field={field}
            value={String((instance.config as Record<string, unknown>)[field.key] ?? "")}
            onSave={(value) => patch.mutateAsync({ config: { [field.key]: value } })}
          />
        ) : (
          <FieldInput
            field={field}
            value={String((instance.config as Record<string, unknown>)[field.key] ?? "")}
            commit="blur"
            onChange={(value) => patch.mutate({ config: { [field.key]: value } })}
          />
        )}
      </SettingsRow>
    </div>
  );

  return (
    <section data-connection={instance.id} className="grid min-w-0 rounded-xl border border-border bg-panel">
      {/* **标题行就是收起 / 展开的按钮**(aria-expanded):收起时一行看清这个连接是什么、此刻怎么样;常用动作
          (刷新、模型库、工作流库、启用开关、删除)收起时也在,不用先展开。要处理的事(停用了要重新授权、缺配置)标黄,
          下面一行写着原因。 */}
      <header className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <Hint label={(open ? t("pluginConnCollapse") : t("pluginConnExpand")).replace("{name}", instance.name)}>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => {
              focusNext.current = open ? null : issue.target ?? null;
              setOpen(!open);
            }}
            className="flex min-w-0 flex-1 basis-[280px] cursor-pointer items-start gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight
              size={16}
              aria-hidden
              className={cn("mt-0.5 shrink-0 text-muted-foreground transition-transform duration-100", open && "rotate-90")}
            />
            <span className="grid min-w-0 flex-1 gap-1">
              <span className="flex min-w-0 items-baseline gap-2">
                <Truncate className="shrink text-ui-md font-semibold text-foreground">{title}</Truncate>
                {address && <Truncate className="timecode shrink-[2] text-ui-xs text-muted-foreground">{address}</Truncate>}
              </span>
              <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-muted-foreground">
                <CatalogBadge tone={issue.tone}>{t(issue.label)}</CatalogBadge>
                {summaryText && <span>{summaryText}</span>}
              </span>
              {issue.detail && (
                /* 只说第一行那句人话;原文(errno、地址)悬停看 —— 并进标题行那条「展开」的说明里(见 tooltip.tsx 的 HintScope) */
                <Truncate lines={2} className={cn("text-ui-xs leading-relaxed", issue.tone === "warning" ? "text-warning" : "text-muted-foreground")}
                          hint={splitErrorText(issue.detail).detail || undefined}>
                  {splitErrorText(issue.detail).summary}
                </Truncate>
              )}
            </span>
          </button>
        </Hint>
        <div className="flex shrink-0 items-center gap-2">
          {(pkg.kind === "mcp" || generates) && (
            <IconButton
              variant="outline"
              size="default"
              className="px-3 text-muted-foreground"
              label={pkg.kind === "mcp" ? t("pluginRefreshTools") : t("pluginRefreshModels")}
              loading={refresh.isPending}
              onClick={() => refresh.mutate()}
            >
              <RefreshCcw size={13} />
            </IconButton>
          )}
          <ConnectionLibraries
            instance={instance}
            workspaceId={workspaceId}
            models={(pkg.provides ?? []).includes("model_library")}
            workflows={(pkg.provides ?? []).includes("workflow_library")}
            onCheckSettings={settingsTarget ? checkSettings : undefined}
          />
          <label className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground">
            <span>{instance.enabled ? t("pluginOn") : t("pluginOff")}</span>
            <Switch checked={instance.enabled} onCheckedChange={(enabled) => patch.mutate({ enabled })} />
          </label>
          <IconButton
            variant="outline"
            size="default"
            className="px-3 text-muted-foreground hover:text-destructive"
            label={t("pluginDeleteConnectionTitle").replace("{name}", instance.name)}
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 size={13} />
          </IconButton>
        </div>
      </header>
      {/* 背后有本机服务的安装目录时,确认框里问要不要一起删、要不要保留模型 */}
      <DeleteConnectionDialog
        packageId={pkg.id}
        hasServices={services.length > 0}
        instance={instance}
        open={confirmDelete}
        onCancel={() => setConfirmDelete(false)}
        onDeleted={() => setConfirmDelete(false)}
      />

      {open && (
      <div
        id={bodyId}
        ref={bodyRef}
        className="grid min-w-0 border-t border-divider px-4 [&>*+*]:border-t [&>*+*]:border-divider"
      >
      {/* 授权是**连接级别**的:写的是这个连接的令牌,管的是这个连接能不能用 —— 所以是正文第一行,
          不在凭据组末尾;长相和下面各行同一套(见 ConnectionAuthorization)。 */}
      {pkg.oauth && instance.authorization && (
        <div data-connection-section="authorization">
          <ConnectionAuthorization instanceId={instance.id} state={instance.authorization} fields={pkg.oauth.fills ?? []} />
        </div>
      )}
      {/* 缺权限停着(插件更新后多要了几项,或刚接上还没授):最上面说清楚为什么、点哪里恢复。 */}
      {(instance.pending_permissions ?? []).length > 0 && (
        <div data-connection-section="permissions">
          <ConnectionPermissionNotice instance={instance} />
        </div>
      )}

      <SettingsRow label={t("pluginConnectionName")} description={t("pluginConnectionNameDesc")}>
        <Input
          className="w-[240px] max-w-full"
          defaultValue={instance.name}
          onBlur={(event) => {
            if (event.target.value.trim() && event.target.value !== instance.name) {
              patch.mutate({ name: event.target.value });
            }
          }}
        />
      </SettingsRow>

      {services.length > 0 && (
        <ConnectionLocalService
          pkg={pkg}
          instance={instance}
          workspaceId={workspaceId}
          serverAddress={serviceAddressField && configRow(serviceAddressField)}
        />
      )}

      {configFields.filter((field) => field !== serviceAddressField).map(configRow)}

      {(pkg.credential_fields ?? []).length > 0 && (
        <div data-connection-section="credentials" className="grid [&>*+*]:border-t [&>*+*]:border-divider">
          <CredentialRows instanceId={instance.id} oauthFields={pkg.oauth?.fills ?? []} />
        </div>
      )}

      {/* 网络是宿主给**每个**连接的一行(不是清单里的配置),排在插件自己声明的配置与凭据之后。 */}
      <div data-connection-section="network">
        <ConnectionNetwork instanceId={instance.id} network={instance.network ?? { mode: "follow", proxy_url: "" }} />
      </div>
      {(instance.package_sources ?? []).length > 0 && (
        <ConnectionPackageSources instanceId={instance.id} sources={instance.package_sources ?? []} />
      )}

      {generates && (
        <div data-connection-section="generation">
          <GenerationModelsRow
            instance={instance}
            status={instance.capability_status?.generation}
            service={localService.data}
            refreshing={refresh.isPending}
            onRefresh={() => refresh.mutate()}
          />
        </div>
      )}

      {(grants.data ?? []).map((grant) => (
        <SettingsRow
          key={grant.permission}
          // 权限是清单里的自由字符串(`network:baidu-pan`),照原样写 —— 但它是一个标识,不是标题:等宽、跟在「权限」后面。
          label={<>{t("permissionRowLabel")} <span className="timecode text-ui-sm font-normal text-muted-foreground">{grant.permission}</span></>}
          description={t("permissionRowDesc")}
        >
          <label className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground">
            <span>{grant.granted ? t("granted") : t("denied")}</span>
            <Switch
              checked={grant.granted}
              onCheckedChange={(granted) => setGrant.mutate({ [grant.permission]: granted })}
            />
          </label>
        </SettingsRow>
      ))}

      {/* 只提供生成的插件没有给智能体和工作流的工具(认领生成的那个工具只给宿主调),
          一张空的勾选表只会让人以为它坏了。 */}
      {(tools.length > 0 || (!generates && !hostOnly)) && (
        <div data-connection-section="tools">
        <CapabilityPicker
          instanceId={instance.id}
          workspaceId={workspaceId}
          tools={tools}
          blockedReason={instance.blocked_reason ?? ""}
          emptyText={noToolsText}
          onToggle={(choices) => setCapabilities.mutate(choices)}
          pending={setCapabilities.isPending}
        />
        </div>
      )}

      <InvocationList instanceId={instance.id} />
      </div>
      )}
    </section>
  );
}

type IssueTone = "success" | "warning" | "muted" | "primary";

/** 目录没刷出来:生成模型那一格或工具表那一格记着的原因。 */
function capabilityError(instance: PluginInstance): string {
  return String(instance.capability_status?.generation?.error || instance.capability_status?.tools?.error || "");
}

/**
 * 一个连接此刻怎么样 —— 收起的那一行上那枚标记、下面那句原因,以及展开时该定位到哪一项(`data-connection-section`)。
 *
 * 先后:用户自己停用的(已停用,不算出错)→ 缺必填配置(定位到那一格)→ 没授权 / 对方不认了(定位到授权那一条)→
 * 缺权限(插件更新后多要了几项 = 需要重新授权;定位到权限那一条)→ 别的不可用原因(缺凭据,定位到凭据)→
 * **背后的本机服务用不了**(按它的状态说,定位到本机服务那一块;见 localServiceStatus.serviceIssue —— 插件那句「检查地址」
 * 只适合「连一台服务器」)→ 目录没刷出来(连不上 ComfyUI 之类,定位到生成模型那一行或工具表)→ 可用。
 */
export function connectionIssue(
  pkg: PluginPackage,
  instance: PluginInstance,
  service?: LocalService | null,
): { tone: IssueTone; label: MessageKey; detail: string; target: string } {
  if (!instance.enabled) return { tone: "muted", label: "pluginConnStateOff", detail: "", target: "" };
  const config = (instance.config ?? {}) as Record<string, unknown>;
  const missing = (pkg.config_fields ?? []).find((field) => field.required && !String(config[field.key] ?? "").trim());
  if (missing) {
    return { tone: "warning", label: "pluginConnStateAction", detail: instance.blocked_reason ?? "", target: `config:${missing.key}` };
  }
  if (instance.authorization === "unauthorized" || instance.authorization === "rejected") {
    return {
      tone: "warning",
      label: instance.authorization === "rejected" ? "pluginConnStateReauth" : "pluginConnStatePending",
      detail: instance.blocked_reason ?? "",
      target: "authorization",
    };
  }
  if ((instance.pending_permissions ?? []).length > 0) {
    return {
      tone: "warning",
      label: instance.permissions_added ? "pluginConnStateReauth" : "pluginConnStatePending",
      detail: instance.blocked_reason ?? "",
      target: "permissions",
    };
  }
  if (instance.blocked_reason) {
    return { tone: "warning", label: "pluginConnStateAction", detail: instance.blocked_reason, target: "credentials" };
  }
  const generationError = instance.capability_status?.generation?.error;
  const toolsError = instance.capability_status?.tools?.error;
  const local = serviceIssue(service, Boolean(capabilityError(instance)));
  if (local) return { tone: local.tone, label: local.label, detail: local.text, target: "local-service" };
  if (generationError || toolsError) {
    return {
      tone: "warning",
      label: "pluginConnStateError",
      detail: String(generationError || toolsError),
      target: generationError ? "generation" : "tools",
    };
  }
  return { tone: "success", label: "pluginConnStateOk", detail: "", target: "" };
}

/** 收起的那一行摆的那项配置(清单的 `summary_field`):枚举给选项的名字;名字里已经写着它就不重复。 */
function summaryAddress(pkg: PluginPackage, instance: PluginInstance): string {
  const field = (pkg.config_fields ?? []).find((one) => one.key === pkg.summary_field);
  if (!field) return "";
  const raw = String(((instance.config ?? {}) as Record<string, unknown>)[field.key] ?? "").trim();
  const options = (field.options ?? []) as { value?: string; label?: string }[];
  const shown = options.find((option) => option.value === raw)?.label ?? raw;
  return shown && !instance.name.includes(shown) ? shown : "";
}

/**
 * 能力勾选:搜索 + 只看已开 + 批量开关。
 *
 * **为什么必须能搜**:一个 MCP 端点报四十上百个工具(TikHub 的 bilibili 报了 41 个),
 * 名字还都是 `bilibili_web_fetch_*` 这种共享长前缀的形态 —— 平铺成一列的话,找一个想要的
 * 要靠肉眼逐行扫过去。搜索框在这里不是锦上添花,是这份列表能不能用的前提。
 */
function CapabilityPicker({
  instanceId,
  workspaceId,
  tools,
  blockedReason,
  emptyText,
  onToggle,
  pending,
}: {
  instanceId: string;
  workspaceId: string;
  tools: ToolState[];
  /** 整个连接为什么还不能用(「未启用」「缺少凭据」…)。空串 = 可以用。
   *  一路传**字符串**而不是布尔:理由在这里被丢掉的话,底下那个灰按钮就再也说不出
   *  自己为什么灰了 —— 而它离显示这句话的组标题有好几百像素。 */
  blockedReason: string;
  /** 一个工具都没有时说什么(为什么空、下一步做什么),由卡片按连接的状态定。 */
  emptyText: string;
  onToggle: (tools: Record<string, boolean>) => void;
  pending: boolean;
}) {
  const t = useI18n();
  const [query, setQuery] = React.useState("");
  const [onlyExposed, setOnlyExposed] = React.useState(false);

  const matched = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    return tools.filter((tool) => {
      if (onlyExposed && !tool.exposed) return false;
      if (!needle) return true;
      // 说明也参与匹配:工具名是 bilibili_web_fetch_* 这种机器名,而用户记得的是"字幕"。它来自的那张工作流的名字、路径也算
      // (ADR 0045:表单和完整工作流各是一个工具,按工作流名搜两个都在)。
      return `${tool.name} ${tool.label} ${toPlainText(tool.description)} ${tool.group?.label ?? ""} ${tool.group?.id ?? ""}`
        .toLowerCase().includes(needle);
    });
  }, [tools, query, onlyExposed]);
  //: 有表单的那几张工作流:完整工作流那一行的副名写「完整工作流」
  const formed = React.useMemo(() => formedGroups(tools), [tools]);

  const exposedCount = tools.filter((tool) => tool.exposed).length;
  // 批量操作只作用于**当前筛出来的**那些 —— 搜了"字幕"再点全选,意思就是"这些字幕相关的全开"。
  //: 记下点的是全开还是全关:存的时候转圈的是那一颗(单个工具的开关自己当场就变了,不算)
  const [bulkTo, setBulkTo] = React.useState<boolean | null>(null);
  const bulk = (exposed: boolean) => {
    setBulkTo(exposed);
    onToggle(Object.fromEntries(matched.map((tool) => [tool.name, exposed])));
  };

  return (
    <SettingsBlock>
      <p className="m-0 text-ui-xs text-muted-foreground">{t("pluginCapabilitiesDesc")}</p>
      {tools.length === 0 ? (
        <p className="m-0 text-xs text-muted-foreground">{emptyText}</p>
      ) : (
        <>
          {/* 和这张卡片上别的输入框同一档高度(标准的 md):此前搜索框写死 h-8、按钮用 sm,
              一行 32px 夹在一列 40px 的字段中间,看着像另一个控件体系。 */}
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="min-w-[180px] flex-1"
              value={query}
              placeholder={t("pluginToolSearch").replace("{n}", String(tools.length))}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button
              variant={onlyExposed ? "default" : "outline"}
              onClick={() => setOnlyExposed((value) => !value)}
            >
              {t("pluginToolOnlyExposed").replace("{n}", String(exposedCount))}
            </Button>
            <Button variant="outline" disabled={pending || !matched.length} loading={pending && bulkTo === true} onClick={() => bulk(true)}>
              {t("pluginToolEnableAll")}
            </Button>
            <Button variant="outline" disabled={pending || !matched.length} loading={pending && bulkTo === false} onClick={() => bulk(false)}>
              {t("pluginToolDisableAll")}
            </Button>
          </div>
          {matched.length === 0 && <p className="m-0 text-xs text-muted-foreground">{t("pluginToolNoMatch")}</p>}
          {/* 列表自己封顶滚动,不把整页撑长:四十个工具铺开之后,下面的「调用记录」和别的
              连接就被顶到几屏之外 —— 而那些是同一张卡片上的东西,不该因为这一段而找不到。
              留 -mx-1 px-1 是给行的焦点环留位置,否则贴着滚动容器边会被裁掉。

              **content-start + auto-rows-min 不能少**:行的根节点带 overflow-hidden,而带
              overflow 的网格项自动最小尺寸失效(min-height:auto 只对 overflow:visible 生效)。
              少了这两个类,41 行会被压进 420px —— 每行成为一条 4px 的横线,里面什么都看不见。 */}
          {/* 不封高度、也不自己滚。**展开一个工具的试运行表单之后,420px 里装不下它** ——
              于是表单在一个内层滚动区里,外面页面还有一条滚动条,两条嵌套着谁也用不顺手。
              工具多(MCP 端点能报四十上百个)靠上面的搜索和「只看已开」收,那是按名字收,
              比按像素截一刀有用得多。 */}
          <div className="-mx-1 grid auto-rows-min content-start gap-1.5 px-1">
            {matched.map((tool) => (
              <ToolRow
                key={tool.name}
                instanceId={instanceId}
                workspaceId={workspaceId}
                tool={tool}
                origin={entryOrigin(tool.group, formed, t)}
                // 传**理由**而不是布尔:一个灰着的按钮不说明自己为什么灰,等于没有反馈。
                blockedReason={blockedReason || (tool.exposed ? "" : t("pluginToolNotExposed"))}
                onToggle={(exposed) => {
                  setBulkTo(null);
                  onToggle({ [tool.name]: exposed });
                }}
              />
            ))}
          </div>
        </>
      )}
    </SettingsBlock>
  );
}


/**
 * 一组设置末尾的动作行。
 *
 * **抽出来是因为已经漂了两份。** 保存按钮写的是 `px-1 pb-1`(没有上内距),授权那块写的是
 * `px-1 pt-2 pb-1` —— 上 8 下 4,方向还是反的,而行本身是 `px-0.5 py-3`。三种刻度叠在一起,
 * 于是"下面那道缝比上面窄"这种事没人能从代码里一眼看出来。
 *
 * 内边距**和行一样**(`px-0.5 py-3`):它排在行的序列里,只有共用同一个节奏才不显得突兀。
 * 不画上边框:组的契约是 `[&>*+*]:border-t`,因为每个子元素都是**一项设置** —— 而这是上面
 * 那组的动作,画一条线等于在它和它所属的东西之间切了一刀,视觉上反倒成了下一项的开头。
 */
//: 导出**只为测试**。这两个组件里各有一处靠肉眼才发现的毛病(两个动作叠成两块、
//: 灰按钮不说明理由),而它们都是结构性的 —— 结构该由测试盯着,不该由下一次截图盯着。
export function CredentialRows({ instanceId, oauthFields }: {
  instanceId: string;
  /** 授权流程会写的那几格(清单 `oauth.stores` 指向的)。它们归授权那一行管(见 ConnectionAuthorization),这里不列。 */
  oauthFields: string[];
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const credentials = useQuery({
    queryKey: ["plugin-credentials", instanceId],
    queryFn: () => listPluginCredentials(instanceId),
  });
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () =>
      savePluginCredentials(instanceId, draft),
    onSuccess: () => {
      setDraft({});
      void qc.invalidateQueries({ queryKey: ["plugin-credentials", instanceId] });
      invalidatePluginDependents(qc);
    },
  });

  const dirty = Object.keys(draft).length > 0;
  const byFlow = new Set(oauthFields);
  const items = (credentials.data ?? []).filter((item) => !byFlow.has(item.key));

  return (
    <>
      {items.map((item) => (
        <SettingsRow
          key={item.key}
          label={item.label}
          description={item.help ? <InlineMarkdown text={item.help} /> : item.filled ? t("pluginCredentialFilled") : t("pluginCredentialEmpty")}
        >
          <Input
            className="w-[240px] max-w-full"
            type={item.secret ? "password" : "text"}
            value={draft[item.key] ?? item.value}
            placeholder={item.key}
            onChange={(event) => setDraft((current) => ({ ...current, [item.key]: event.target.value }))}
          />
        </SettingsRow>
      ))}
      {/* 整组一次提交,不逐格失焦即存:密钥输错一个字符和输对长得一模一样,而逐格自动保存
          会让"改了一半"和"改完了"在后端无法区分 —— 改到一半正好等于一条连不上的连接。
          一个显式的保存按钮同时也是"现在去重连试试"的时机。

          **所以它是一个,不是每行一个。** 此前这个按钮画在 map 里,而它的显示条件
          (`draft` 非空)是整组的:改任何一格,每一行都长出一个按钮,四个密钥就是四个
          "保存",点哪个都一样 —— 看起来像四件事,其实是同一件。 */}
      {dirty && (
        <GroupActions>
          <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
            <KeyRound size={13} /> {t("pluginCredentialsSave")}
          </Button>
        </GroupActions>
      )}
    </>
  );
}

interface ToolState {
  name: string;
  label: string;
  description: string;
  read_only: boolean;
  /** 后果(none / paid / external / local-code)。不是 none 的,智能体调它之前先开确认卡。 */
  effects: string;
  input_schema?: { [key: string]: unknown };
  exposed: boolean;
  /** 试跑表单的字段:和这个工具当工作流节点时**同一份声明**(后端节点目录的形状,已按语言翻好)。 */
  form?: { [key: string]: unknown };
  /** 它认领的调用类能力(文档解析、降噪……):它照样是一个普通工具,能力是加在它上面的一份契约(ADR 0033)。 */
  provides?: string[];
  /** 这些能力在 Mosael 里还用在哪(能力表现算的)—— 那些入口调的也是这个工具。 */
  used_by?: CapabilityUse[];
  /** 是哪张工作流的哪个入口(ADR 0045;ComfyUI 的完整工作流和它的表单)。 */
  group?: EntryGroup | null;
  /** 进不进智能体的工具表;插件说 `agent: false` 的不进(工作流节点、画板照常)。 */
  agent?: boolean;
}

/** 表单里的一格有没有填。素材列表空着、字符串空着都算没填(不发出去)。 */
function filled(value: unknown): boolean {
  if (value === undefined || value === null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

/** 工具行:左边一个「暴不暴露」的勾,展开后按 input_schema 生成表单试跑。
 *
 * **记忆化**:改一个勾会重新拉整份 /api/plugins,41 行随之重渲染 —— 而展开着大结果的那几行
 * 每次都要把那段文本重新排版一次。props 没变就别重渲染。 */
export const ToolRow = React.memo(function ToolRow({
  instanceId,
  workspaceId,
  tool,
  origin = "",
  blockedReason,
  onToggle,
}: {
  instanceId: string;
  workspaceId: string;
  tool: ToolState;
  /** 两层名字的副名里「这是哪个入口」那一截(「来自 X」/「完整工作流」,ADR 0045);不给 / 空串不写。 */
  origin?: string;
  /** 为什么这个工具现在跑不了。空串 = 跑得了。 */
  blockedReason: string;
  onToggle: (exposed: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const { labelOf } = useCapabilityTerms();
  const [open, setOpen] = React.useState(false);
  const [result, setResult] = React.useState<PluginInvocation | null>(null);

  const invoke = useMutation({
    mutationFn: (config: Record<string, unknown>) => {
      // 数字、开关按工具的入参声明转回类型是后端的事(plugins/inputs.coerce):工作流节点送来的也是这些字符串,
      // 两条路同一个规矩。这里只把没填的去掉。
      const input = Object.fromEntries(Object.entries(config).filter(([, value]) => filled(value)));
      return invokePluginTool(instanceId, tool.name, { input, workspace_id: workspaceId });
    },
    onSuccess: (invocation) => {
      setResult(invocation);
      void qc.invalidateQueries({ queryKey: ["plugin-invocations", instanceId] });
      if (invocation.status === "succeeded" && invocation.output.asset_id) {
        void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      }
    },
  });

  return (
    <ToolRowFrame
      // 勾 = 暴不暴露给智能体和工作流。默认关 —— 一个 MCP 端点可能报几十个工具。
      lead={<Checkbox checked={tool.exposed} onCheckedChange={(next) => onToggle(next === true)} aria-label={tool.name} />}
      label={tool.label || tool.name}
      origin={origin}
      description={tool.description}
      badges={<>
        {/* 认领了宿主能力的,标一枚能力徽标:MinerU 的解析同时是文档「重新解析」背后那一家。 */}
        {(tool.provides ?? []).map((capability) => (
          <small key={capability} data-tool-capability={capability}
            className="whitespace-nowrap rounded-full bg-accent px-1.5 py-px text-ui-2xs text-primary">
            {labelOf(capability)}
          </small>
        ))}
        {tool.read_only && (
          <small className="whitespace-nowrap rounded-full bg-secondary px-1.5 py-px text-ui-2xs text-muted-foreground">
            {t("pluginToolReadOnly")}
          </small>
        )}
        {/* 插件说它不进智能体的工具表(有表单的工作流,给智能体的是表单那一项,ADR 0045 §5):开着也只在工作流、画板里用 */}
        {tool.agent === false && (
          <Hint label={t("pluginToolNotForAgentHint")}>
            <small data-tool-not-for-agent="" className="whitespace-nowrap rounded-full bg-secondary px-1.5 py-px text-ui-2xs text-muted-foreground">
              {t("pluginToolNotForAgent")}
            </small>
          </Hint>
        )}
        <ToolEffectBadge effects={tool.effects} />
      </>}
      open={open}
      onOpenChange={setOpen}
    >
      {(tool.used_by ?? []).length > 0 && <CapabilityUseList uses={tool.used_by ?? []} label={t("capabilityUsedBy")} />}
      <ToolTryForm
        tool={tool}
        workspaceId={workspaceId}
        blockedReason={blockedReason}
        pending={invoke.isPending}
        onRun={(config) => invoke.mutate(config)}
      />
      {result && <ResultBlock ok={result.status === "succeeded"} body={result.status === "succeeded" ? result.output : result.error ?? result.status} />}
    </ToolRowFrame>
  );
});

/**
 * 工具的「试一下」表单:**用工作流节点的那个表单组件**(NodeConfigForm)渲染后端给的同一份字段声明 ——
 * 名字是人话、说明按行内 Markdown 渲染、素材字段是素材选择器(一串素材是挑出来的一排,不是 JSON 框)、
 * 可选值是下拉、数字是数字框、留空也能跑的收进「高级选项」。
 *
 * 此前这里按 input_schema 自己拼:标签是裸键名、每个输入框的占位都是 `string`、一串图要手写 `[]`。
 * 同一个工具在工作流里是一张像样的表单,在插件页却是这副样子 —— 两处各写一遍的结果。
 */
export function ToolTryForm({
  tool,
  workspaceId,
  blockedReason,
  pending,
  onRun,
}: {
  tool: ToolState;
  workspaceId: string;
  blockedReason: string;
  pending: boolean;
  onRun: (config: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const specs = React.useMemo(() => (tool.form ?? {}) as Record<string, ConfigSpec>, [tool.form]);
  const [config, setConfig] = React.useState<Record<string, unknown>>({});
  const [showAdvanced, setShowAdvanced] = React.useState(false);
  const fieldOptions = useNodeFieldOptions({ specs, config, workspaceId, nodeType: "" });
  const { basic, advanced } = nodeConfigTiers(specs, config);
  const set = (key: string, value: unknown) => setConfig((current) => ({ ...current, [key]: value }));
  const patch = (next: Record<string, unknown>) => setConfig((current) => ({ ...current, ...next }));
  const missingRequired = Object.entries(specs).some(([key, spec]) => spec?.required && !filled(config[key]));
  const form = (fields: Array<[string, ConfigSpec]>) => (
    <NodeConfigForm
      fields={fields}
      config={config}
      workspaceId={workspaceId}
      variables={[]}
      fieldOptions={fieldOptions}
      onSetConfig={set}
      onTypeConfig={set}
      onPatchConfig={(_owner, next) => patch(next)}
    />
  );
  return (
    <>
      {basic.length > 0 && <div className="grid gap-4">{form(basic)}</div>}
      {advanced.length > 0 && (
        <Disclosure label={t("wfAdvanced")} count={advanced.length} open={showAdvanced} onOpenChange={setShowAdvanced}
                    contentClassName="pt-4">
          {form(advanced)}
        </Disclosure>
      )}
      {/* **把理由摆在按钮旁边。** 「未启用」这句话本来只写在整组的标题下,而工具行
          可能在它下面好几百像素处 —— 用户看到的就只是一个灰着的按钮,试不出所以然。
          缺必填参数同理:不说的话,他会以为是插件坏了。 */}
      <div className="flex items-center justify-end gap-2">
        {(blockedReason || missingRequired) && (
          <Truncate as="small" className="text-ui-xs text-muted-foreground">
            {blockedReason || t("pluginToolMissingRequired")}
          </Truncate>
        )}
        <Button size="sm" disabled={Boolean(blockedReason) || missingRequired} loading={pending} onClick={() => onRun(config)}>
          <Play size={13} /> {t("runTool")}
        </Button>
      </div>
    </>
  );
}

function InvocationList({ instanceId }: { instanceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const invocations = useQuery({
    queryKey: ["plugin-invocations", instanceId],
    queryFn: () => listPluginInvocations(instanceId),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["plugin-invocations", instanceId] });
  const clear = useMutation({
    mutationFn: () => clearPluginInvocations(instanceId),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => removePluginInvocation(id),
    onSuccess: invalidate,
  });

  const rows = invocations.data ?? [];
  if (rows.length === 0) return null;

  return (
    <SettingsBlock>
      <div className="flex items-center justify-between">
        <p className="m-0 text-ui-xs text-muted-foreground">{t("invocationsGroupDesc")}</p>
        <Button variant="outline" size="sm" loading={clear.isPending} onClick={() => clear.mutate()}>
          <Trash2 size={13} /> {t("invocationsClear")}
        </Button>
      </div>
      {rows.slice(0, 10).map((invocation) => (
        <InvocationRow key={invocation.id} invocation={invocation} onDelete={() => remove.mutate(invocation.id)} />
      ))}
    </SettingsBlock>
  );
}

function InvocationRow({ invocation, onDelete }: { invocation: PluginInvocation; onDelete: () => void }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const ok = invocation.status === "succeeded";
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-panel">
      <div className="flex items-stretch [&>button:first-child]:min-w-0 [&>button:first-child]:flex-1">
        <button
          type="button"
          className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent px-2 py-[9px] text-left hover:bg-secondary"
          onClick={() => setOpen((value) => !value)}
        >
          {ok ? <CheckCircle2 size={14} className="text-success" /> : <CircleAlert size={14} className="text-destructive" />}
          <div className="min-w-0 [&_strong]:block [&_strong]:text-ui-sm [&_strong]:font-semibold">
            <strong>{invocation.tool_name}</strong>
            <Truncate as="small" className="text-ui-xs text-muted-foreground">{invocation.status}</Truncate>
          </div>
        </button>
        <IconButton
          unstyled
          type="button"
          className="grid w-8 flex-none cursor-pointer place-items-center border-0 bg-transparent text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-destructive"
          label={t("delete")}
          onClick={onDelete}
        >
          <Trash2 size={13} />
        </IconButton>
      </div>
      {open && <ResultBlock ok={ok} body={ok ? invocation.output : { input: invocation.input, error: invocation.error }} />}
    </div>
  );
}

/**
 * 渲染上限。超出的**不进 DOM**,只留一行说明 + 复制全部。
 *
 * 判据是实测的:一段 341KB 的 JSON 放进 `whitespace-pre-wrap` + `word-break` 的 `<pre>` 里,
 * 光排版就要 **59ms**(JSON.stringify 只占 1ms —— 慢的从来不是序列化,是让浏览器给三十万个
 * 字符逐个算折行位置)。`max-h` 挡不住这笔开销:要知道能不能滚,浏览器必须先把全部内容排完。
 * 展开几个这样的工具,每次重渲染都要重付一遍,整页就卡住了。
 *
 * 8000 字符在 200px 的框里已经要滚很久;真要看全的人需要的是复制出去,不是在这里翻。
 */
const RESULT_RENDER_LIMIT = 8000;

function ResultBlock({ ok, body }: { ok: boolean; body: unknown }) {
  const t = useI18n();
  // 序列化本身不贵,但没必要每次重渲染都跑;真正要防的是下面那段文本被重新排版。
  // **先展开"被编码成字符串的 JSON"**:MCP 这一侧很常见(FastMCP 把字符串返回值包进
  // `result`),直接 stringify 会把那层转义再转义一遍 —— 中文变 \u 转义、换行变字面的
  // \n,一份结构清晰的场景数据糊成一整片。见 invocationResult.ts。
  const full = React.useMemo(() => formatInvocationResult(body), [body]);
  const clipped = full.length > RESULT_RENDER_LIMIT;
  const shown = clipped ? full.slice(0, RESULT_RENDER_LIMIT) : full;
  return (
    // **一条分割线,不是又一个框。** 外面那张卡片已经有边框了,结果再套一层带色边框 + 圆角 +
    // 独立底色就成了"框中框",而它并不表达任何新东西 —— 成败在卡片顶部已经由图标和状态文字
    // 说过一遍。失败时只留文字用红色,那是**这段内容本身**的属性,不需要给它画一个红盒子。
    <div className="grid gap-1 border-t border-divider px-2 pb-2 pt-2">
      <pre
        className={cn(
          "m-0 max-h-[200px] overflow-auto whitespace-pre-wrap font-mono text-ui-xs leading-[1.5] [word-break:break-word]",
          ok ? "text-muted-foreground" : "text-destructive",
        )}
      >
        {shown}
      </pre>
      {clipped && (
        <div className="flex items-center justify-between gap-2 text-ui-xs text-muted-foreground">
          <span>
            {t("pluginResultClipped")
              .replace("{shown}", String(RESULT_RENDER_LIMIT))
              .replace("{total}", full.length.toLocaleString())}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-ui-xs"
            onClick={() => void navigator.clipboard?.writeText(full)}
          >
            <Copy size={11} /> {t("pluginResultCopyAll")}
          </Button>
        </div>
      )}
    </div>
  );
}
