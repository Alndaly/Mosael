import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  CheckCircle2,
  Copy,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  KeyRound,
  Play,
  Plug,
  Plus,
  RefreshCcw,
  Terminal,
  Store,
  Trash2,
} from "lucide-react";

import {
  api,
  type PluginField,
  type PluginInstance,
  type PluginInvocation,
  type PluginPackage,
  type PluginPermissionGrant,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/layout/EmptyState";
import { ModalShell } from "@/components/app/modals";
import { PluginMarketDialog } from "@/features/plugins/PluginMarket";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Skeleton } from "@/components/ui/skeleton";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { usePersistentSelection, usePersistentTab } from "@/lib/usePersistentTab";
import { COMPACT_SIDEBAR_BOUNDS, useResizableSidebar } from "@/lib/useResizableSidebar";
import { cn } from "@/lib/utils";

/**
 * 插件页 = 包 → 连接 → 能力 三层。
 *
 * 左边列的是**包**(磁盘上装了什么),右边是这个包的**连接**(一次具体接入:配置 + 凭据 +
 * 启用 + 勾了哪些工具)。一个包可以有多个连接 —— TikHub 一个包对应十几个平台端点,
 * B站一个、抖音一个,各有各的凭据和名字。
 *
 * 设计与取舍见 docs/PLUGIN_ARCHITECTURE.md。
 */
export function PluginsView() {
  // 右栏现在是一块有边框的面板,它的边**就是**列边界 —— 不再需要 nextInset 补偿
  // (那是给"无边框滚动容器 + 内层 px-0.5"那种形状用的,见 handleOffset)。
  const sidebar = useResizableSidebar("plugins", COMPACT_SIDEBAR_BOUNDS);
  const t = useI18n();
  const qc = useQueryClient();

  const packages = useQuery({ queryKey: ["plugins"], queryFn: () => api<PluginPackage[]>("/api/plugins") });
  // 插件目录由后端算、后端报:Windows 上它不是 `~/.mosael/`,文案里写死找不到地方。
  const pluginsDir = useQuery({
    queryKey: ["plugins-dir"],
    queryFn: () => api<{ path: string }>("/api/plugins/dir"),
    staleTime: Infinity,
  });
  const scan = useMutation({
    mutationFn: () => api<PluginPackage[]>("/api/plugins/scan", { method: "POST" }),
    onSuccess: () => invalidatePlugins(qc),
  });

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
  //: 一个插件都没有时**自己把市场打开** —— 「已安装」那一栏这时只会说「你没有插件」,
  //: 而那句话帮不上任何忙。只在「从有到无」这一刻弹一次:用户关掉之后不该再弹回来。
  const empty = packages.isSuccess && list.length === 0;
  React.useEffect(() => {
    if (empty) setMarketOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empty]);
  const selected = list.find((item) => item.id === selectedId) ?? list[0] ?? null;


  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-2 [&>*]:shrink-0">
      <div className="relative grid min-h-0 flex-1 gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]"
        style={{ gridTemplateColumns: `${sidebar.width}px minmax(0, 1fr)` }}>
        <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[880px]:flex max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:px-1.5 max-[880px]:py-[5px] max-[880px]:[&>div:first-child]:contents">
          <div className="flex min-h-10 items-center justify-between border-b border-border px-3">
            {/* 「插件」而不是「已安装」:这一栏和右边的详情是**同一件东西的两半**,而标题是在
                回答"这一栏里是什么",不是在给它们贴状态 —— 没装的插件根本不会出现在这儿。 */}
            <span className="text-ui-xs font-semibold uppercase tracking-[0.06em] text-foreground">
              {t("pluginsTitle")}
            </span>
            <span className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 px-2 text-ui-2xs"
                onClick={() => setMarketOpen(true)}
              >
                <Store size={12} /> {t("pluginMarket")}
              </Button>
              <ScanButton pending={scan.isPending} onScan={() => scan.mutate()} />
            </span>
          </div>
          <div className="grid content-start gap-1 overflow-y-auto p-1.5 max-[880px]:order-1 max-[880px]:flex max-[880px]:min-w-0 max-[880px]:flex-1 max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:overflow-x-auto max-[880px]:p-0">
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
              const live = (item.instances ?? []).filter((i) => i.enabled).length;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cn(
                    "flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted max-[880px]:shrink-0 max-[880px]:py-1",
                    selected?.id === item.id && "bg-accent hover:bg-accent",
                  )}
                  onClick={() => setSelectedId(item.id)}
                >
                  <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", live > 0 && "bg-success")} />
                  <span className="min-w-0 [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-ui-sm [&_strong]:font-semibold max-[880px]:[&_small]:hidden">
                    <strong>{item.name}</strong>
                    <small>
                      v{item.version} · {t("pluginConnectionCount").replace("{n}", String((item.instances ?? []).length))}
                    </small>
                  </span>
                </button>
              );
            })}
            {packages.isSuccess && list.length === 0 && (
              <p className="m-0 px-2 py-3 text-ui-xs leading-[1.6] text-muted-foreground">
                {t("noPluginsGuide").replace("{dir}", pluginsDir.data?.path ?? "")}
              </p>
            )}
          </div>
        </aside>
        {/* 边缘拖动 —— 和剪辑页同一套(lib/useResizableSidebar)。 */}
        <div {...sidebar.handleProps} />

      {/* 市场:**一张弹窗,宽度归它自己** —— 挤在侧栏里时,一个用来浏览的列表被塞进了
          一个用来选中的列表的位置,每张卡片的说明都要折成五行。 */}
      {/* 搜索条钉在头里、列表在滚动体里 —— 滚动由 ModalShell 那一层管,这里**不再自己套一层
          overflow**:套两层的后果是标题跟着列表滚走,而且贴着裁剪线的搜索框焦点框会缺半圈。 */}
      <PluginMarketDialog open={marketOpen} onOpenChange={setMarketOpen} onInstalled={() => invalidatePlugins(qc)} />
        {/* 右栏是**一块占满高度的面板**,内部滚动。详情从顶部开始;没有选中项时则让空状态
            在整块可用区域内真正居中,而不是被 content-start 锁在顶部。 */}
        <div
          className={cn(
            "grid min-h-0 min-w-0 overflow-y-auto rounded-md border border-border bg-panel px-3 py-2.5 shadow-[var(--shadow-panel)]",
            selected ? "content-start" : "place-items-center",
          )}
        >
          {selected ? (
            <PackageDetail key={selected.id} pkg={selected} />
          ) : (
            <EmptyState icon={<Plug size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>
    </div>
  );
}

function invalidatePlugins(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["plugins"] });
  void qc.invalidateQueries({ queryKey: ["plugin-tools"] });
  void qc.invalidateQueries({ queryKey: ["workflow-node-types"] });
}

/** 扫描按钮:pending 时图标转起来、文案改成「扫描中」—— 以前只是 disabled,点下去像没点上。 */
function ScanButton({ pending, onScan, size = "sm" }: { pending: boolean; onScan: () => void; size?: "sm" | "default" }) {
  const t = useI18n();
  const label = pending ? t("scanningPlugins") : t("scanPlugins");
  // 列表头上是**只有图标的圆钮**:那一行已经有「已安装」在说这是什么,再写一遍"扫描插件"
  // 只是把标题挤窄。空状态里那个是主动作(整页就它一个按钮),文案得留着。
  // 两处都在扫描时禁用并转圈 —— 扫描要走磁盘,连点两下就是两趟。
  if (size === "sm") {
    return (
      <Button
        variant="outline"
        size="icon"
        className="h-7 w-7 rounded-full"
        title={label}
        aria-label={label}
        disabled={pending}
        onClick={onScan}
      >
        <RefreshCcw size={13} className={pending ? "animate-mosael-spin" : undefined} />
      </Button>
    );
  }
  return (
    <Button size="default" disabled={pending} onClick={onScan}>
      <RefreshCcw size={15} className={pending ? "animate-mosael-spin" : undefined} />
      {label}
    </Button>
  );
}

function PackageDetail({ pkg }: { pkg: PluginPackage }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [confirmUninstall, setConfirmUninstall] = React.useState(false);
  const [draft, setDraft] = React.useState<Record<string, string>>({});

  const uninstall = useMutation({
    mutationFn: () => api(`/api/plugins/${pkg.id}`, { method: "DELETE" }),
    onSuccess: () => {
      setConfirmUninstall(false);
      invalidatePlugins(qc);
    },
  });
  const createInstance = useMutation({
    mutationFn: () =>
      api<PluginInstance>(`/api/plugins/${pkg.id}/instances`, {
        method: "POST",
        body: JSON.stringify({ config: draft }),
      }),
    onSuccess: () => {
      setDraft({});
      invalidatePlugins(qc);
    },
  });

  const canAdd = pkg.multiple || (pkg.instances ?? []).length === 0;

  const instances = pkg.instances ?? [];
  const live = instances.filter((one) => one.enabled).length;

  return (
    <div className="grid w-full content-start gap-4">
      {/* 卸载会删掉磁盘上的插件目录 —— 不可撤销,所以走确认。 */}
      <ConfirmDialog
        open={confirmUninstall}
        title={t("pluginUninstallTitle").replace("{name}", pkg.name)}
        body={t("pluginUninstallBody")}
        onCancel={() => setConfirmUninstall(false)}
        onConfirm={() => uninstall.mutate()}
      />

      {/* **页头,不是卡片。** 包是这一页的身份 —— 它此前和连接一样是个 SettingsGroup,
          于是「TikHub」在屏幕上出现两次、长得一模一样,读的人分不清哪个是包哪个是连接。
          身份该在版面顶端只出现一次,后面全是它的内容。 */}
      <header className="grid gap-2 border-b border-border pb-3">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 truncate text-ui-lg font-semibold text-foreground">{pkg.name}</h2>
          <span className="flex shrink-0 items-center gap-1">
            {/* **文档由插件自己给。** 一个插件带来四十个工具、一串权限和一套要去哪儿申请的
                凭据 —— 这些怎么用只有作者说得清,我们能做的是把人送到那儿。清单里没写就不画,
                画一个点不开的按钮比没有更糟。 */}
            {pkg.homepage && (
              <Button variant="ghost" size="sm" className="text-muted-foreground" asChild>
                <a href={pkg.homepage} target="_blank" rel="noreferrer noopener">
                  <BookOpen size={13} /> {t("pluginDocs")}
                </a>
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0 text-muted-foreground hover:text-destructive"
              loading={uninstall.isPending}
              onClick={() => setConfirmUninstall(true)}
            >
              <Trash2 size={13} /> {t("pluginUninstall")}
            </Button>
          </span>
        </div>
        {/* 元信息一行说完 —— 它们是查故障时才看的东西,不值一整块版面。 */}
        <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-muted-foreground">
          <span className="timecode">{pkg.id}</span>
          <span aria-hidden>·</span>
          <span>v{pkg.version}</span>
          <span aria-hidden>·</span>
          <span>{pkg.kind === "mcp" ? t("pluginKindMcp") : t("pluginKindProcess")}</span>
          {live > 0 && (
            <>
              <span aria-hidden>·</span>
              <span className="text-success">{t("pluginConnectionCount").replace("{n}", String(live))}</span>
            </>
          )}
        </p>
      </header>

      {/* 连接是这一页的**主体**。有几个就是几个,新建那一条排在最后 —— 排在最前的话,
          每次进来第一眼看到的是"再建一个",而绝大多数时候用户是来改已有的那个。 */}
      {instances.map((instance) => (
        <ConnectionCard key={instance.id} pkg={pkg} instance={instance} />
      ))}

      {instances.length === 0 && (
        <EmptyState size="compact" icon={<Plug size={15} />} title={t("pluginNoConnections")} body={t("pluginNoConnectionsBody")} />
      )}

      {canAdd && (
        <div className="grid gap-2 rounded-lg border border-dashed border-border px-3 py-2.5">
          <span className="text-ui-sm font-semibold text-foreground">{t("pluginNewConnection")}</span>
          <p className="m-0 text-ui-xs leading-[1.55] text-muted-foreground">
            {(pkg.config_fields ?? []).length ? t("pluginNewConnectionDesc") : t("pluginNewConnectionSimple")}
          </p>
          {/* 字段**铺满这一行**,按钮跟在末尾。此前是 flex-wrap + 各自按内容宽度:只有一个
              字段时,那一格就是一小块漂在一整行空白里,读起来像这块没做完。 */}
          <div className="flex flex-wrap items-center gap-1.5 [&>*:not(:last-child)]:min-w-0 [&>*:not(:last-child)]:flex-1">
            {(pkg.config_fields ?? []).map((field) => (
              <FieldInput
                key={field.key}
                field={field}
                value={draft[field.key] ?? field.default}
                onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}
              />
            ))}
            <Button className="shrink-0" size="sm" loading={createInstance.isPending} onClick={() => createInstance.mutate()}>
              <Plus size={13} /> {t("pluginAddConnection")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 一个配置项 / 凭据项的控件。枚举给下拉、开关给 Switch,别的给文本框 —— 类型是声明出来的。 */
function FieldInput({
  field,
  value,
  onChange,
}: {
  field: PluginField;
  value: string;
  onChange: (value: string) => void;
}) {
  const t = useI18n();
  if (field.type === "enum") {
    return (
      <SearchableSelect
        className="w-[180px]"
        value={value}
        onValueChange={onChange}
        placeholder={t("pluginPickField").replace("{label}", field.label)}
        options={(field.options as { value: string; label: string }[]).map((option) => ({
          value: option.value,
          label: option.label,
        }))}
      />
    );
  }
  return (
    <Input
      className="w-[220px] max-w-full"
      type={field.secret ? "password" : field.type === "number" ? "number" : "text"}
      value={value}
      placeholder={field.label}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function ConnectionCard({ pkg, instance }: { pkg: PluginPackage; instance: PluginInstance }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<PluginInstance>(`/api/plugins/instances/${instance.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => invalidatePlugins(qc),
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/plugins/instances/${instance.id}`, { method: "DELETE" }),
    onSuccess: () => {
      setConfirmDelete(false);
      invalidatePlugins(qc);
    },
  });
  const refresh = useMutation({
    mutationFn: () => api<PluginInstance>(`/api/plugins/instances/${instance.id}/refresh`, { method: "POST" }),
    onSuccess: () => invalidatePlugins(qc),
  });
  const setCapabilities = useMutation({
    mutationFn: (tools: Record<string, boolean>) =>
      api<PluginInstance>(`/api/plugins/instances/${instance.id}/capabilities`, {
        method: "PATCH",
        body: JSON.stringify({ tools }),
      }),
    onSuccess: () => invalidatePlugins(qc),
  });

  const grants = useQuery({
    queryKey: ["plugin-permissions", instance.id],
    queryFn: () => api<PluginPermissionGrant[]>(`/api/plugins/instances/${instance.id}/permissions`),
    enabled: (pkg.permissions ?? []).length > 0,
  });
  const setGrant = useMutation({
    mutationFn: (grantsBody: Record<string, boolean>) =>
      api<PluginPermissionGrant[]>(`/api/plugins/instances/${instance.id}/permissions`, {
        method: "PATCH",
        body: JSON.stringify({ grants: grantsBody }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plugin-permissions", instance.id] });
      invalidatePlugins(qc);
    },
  });

  const exposedCount = (instance.tools ?? []).filter((tool) => tool.exposed).length;

  return (
    <SettingsGroup
      title={instance.name}
      description={
        instance.blocked_reason
          ? instance.blocked_reason
          : t("pluginExposedCount").replace("{n}", String(exposedCount)).replace("{total}", String((instance.tools ?? []).length))
      }
      actions={
        <div className="flex items-center gap-2">
          <label className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-muted-foreground">
            <span>{instance.enabled ? t("pluginOn") : t("pluginOff")}</span>
            <Switch checked={instance.enabled} onCheckedChange={(enabled) => patch.mutate({ enabled })} />
          </label>
          {pkg.kind === "mcp" && (
            <Button variant="outline" size="sm" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              <RefreshCcw size={13} />
              {t("pluginRefreshTools")}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => setConfirmDelete(true)}
          >
            <Trash2 size={13} />
          </Button>
        </div>
      }
    >
      <ConfirmDialog
        open={confirmDelete}
        title={t("pluginDeleteConnectionTitle").replace("{name}", instance.name)}
        body={t("pluginDeleteConnectionBody")}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
      />

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

      {(pkg.config_fields ?? []).map((field) => (
        <SettingsRow key={field.key} label={field.label} description={field.help}>
          <FieldInput
            field={field}
            value={String((instance.config as Record<string, unknown>)[field.key] ?? "")}
            onChange={(value) => patch.mutate({ config: { [field.key]: value } })}
          />
        </SettingsRow>
      ))}

      {(pkg.credential_fields ?? []).length > 0 && <CredentialRows instanceId={instance.id} />}

      {(grants.data ?? []).map((grant) => (
        <SettingsRow key={grant.permission} label={grant.permission} description={t("permissionRowDesc")}>
          <label className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-muted-foreground">
            <span>{grant.granted ? t("granted") : t("denied")}</span>
            <Switch
              checked={grant.granted}
              onCheckedChange={(granted) => setGrant.mutate({ [grant.permission]: granted })}
            />
          </label>
        </SettingsRow>
      ))}

      <CapabilityPicker
        instanceId={instance.id}
        tools={instance.tools ?? []}
        blocked={Boolean(instance.blocked_reason)}
        onToggle={(tools) => setCapabilities.mutate(tools)}
        pending={setCapabilities.isPending}
      />

      <InvocationList instanceId={instance.id} />
    </SettingsGroup>
  );
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
  tools,
  blocked,
  onToggle,
  pending,
}: {
  instanceId: string;
  tools: ToolState[];
  blocked: boolean;
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
      // 说明也参与匹配:工具名是 bilibili_web_fetch_* 这种机器名,而用户记得的是"字幕"。
      return `${tool.name} ${tool.label} ${tool.description}`.toLowerCase().includes(needle);
    });
  }, [tools, query, onlyExposed]);

  const exposedCount = tools.filter((tool) => tool.exposed).length;
  // 批量操作只作用于**当前筛出来的**那些 —— 搜了"字幕"再点全选,意思就是"这些字幕相关的全开"。
  const bulk = (exposed: boolean) => onToggle(Object.fromEntries(matched.map((tool) => [tool.name, exposed])));

  return (
    <SettingsBlock>
      <p className="m-0 text-ui-xs text-muted-foreground">{t("pluginCapabilitiesDesc")}</p>
      {tools.length === 0 ? (
        <p className="m-0 text-xs text-muted-foreground">{t("noTools")}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <Input
              className="h-8 min-w-[180px] flex-1"
              value={query}
              placeholder={t("pluginToolSearch").replace("{n}", String(tools.length))}
              onChange={(event) => setQuery(event.target.value)}
            />
            <Button
              variant={onlyExposed ? "default" : "outline"}
              size="sm"
              onClick={() => setOnlyExposed((value) => !value)}
            >
              {t("pluginToolOnlyExposed").replace("{n}", String(exposedCount))}
            </Button>
            <Button variant="outline" size="sm" disabled={pending || !matched.length} onClick={() => bulk(true)}>
              {t("pluginToolEnableAll")}
            </Button>
            <Button variant="outline" size="sm" disabled={pending || !matched.length} onClick={() => bulk(false)}>
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
          <div className="-mx-1 grid max-h-[420px] auto-rows-min content-start gap-1.5 overflow-y-auto px-1">
            {matched.map((tool) => (
              <ToolRow
                key={tool.name}
                instanceId={instanceId}
                tool={tool}
                runnable={!blocked && tool.exposed}
                onToggle={(exposed) => onToggle({ [tool.name]: exposed })}
              />
            ))}
          </div>
        </>
      )}
    </SettingsBlock>
  );
}

function CredentialRows({ instanceId }: { instanceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  type Credential = { key: string; label: string; help: string; secret: boolean; filled: boolean; value: string };
  const credentials = useQuery({
    queryKey: ["plugin-credentials", instanceId],
    queryFn: () => api<Credential[]>(`/api/plugins/instances/${instanceId}/credentials`),
  });
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () =>
      api<Credential[]>(`/api/plugins/instances/${instanceId}/credentials`, {
        method: "PATCH",
        body: JSON.stringify({ values: draft }),
      }),
    onSuccess: () => {
      setDraft({});
      void qc.invalidateQueries({ queryKey: ["plugin-credentials", instanceId] });
      invalidatePlugins(qc);
    },
  });

  return (
    <>
      {(credentials.data ?? []).map((item) => (
        <SettingsRow
          key={item.key}
          label={item.label}
          description={item.help || (item.filled ? t("pluginCredentialFilled") : t("pluginCredentialEmpty"))}
        >
          <div className="flex items-center gap-1.5">
            <Input
              className="w-[240px] max-w-full"
              type={item.secret ? "password" : "text"}
              value={draft[item.key] ?? item.value}
              placeholder={item.key}
              onChange={(event) => setDraft((current) => ({ ...current, [item.key]: event.target.value }))}
            />
            {/* 整组一次提交,不逐格失焦即存:密钥输错一个字符和输对长得一模一样,而逐格
                自动保存会让"改了一半"和"改完了"在后端无法区分 —— 改到一半正好等于一条连不上
                的连接。一个显式的保存按钮同时也是"现在去重连试试"的时机。 */}
            {Object.keys(draft).length > 0 && (
              <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
                <KeyRound size={13} /> {t("pluginCredentialsSave")}
              </Button>
            )}
          </div>
        </SettingsRow>
      ))}
    </>
  );
}

interface ToolState {
  name: string;
  label: string;
  description: string;
  read_only: boolean;
  input_schema?: { [key: string]: unknown };
  exposed: boolean;
}

/** 工具的入参模式:生成的类型只知道它是个对象,这里收一次窄化,免得每处各写一遍断言。 */
type InputSchema = { properties?: Record<string, { type?: string; description?: string }>; required?: string[] };

/** 工具行:左边一个「暴不暴露」的勾,展开后按 input_schema 生成表单试跑。
 *
 * **记忆化**:改一个勾会重新拉整份 /api/plugins,41 行随之重渲染 —— 而展开着大结果的那几行
 * 每次都要把那段文本重新排版一次。props 没变就别重渲染。 */
const ToolRow = React.memo(function ToolRow({
  instanceId,
  tool,
  runnable,
  onToggle,
}: {
  instanceId: string;
  tool: ToolState;
  runnable: boolean;
  onToggle: (exposed: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<PluginInvocation | null>(null);

  const schema = (tool.input_schema ?? {}) as InputSchema;
  const fields = Object.entries(schema.properties ?? {});
  const required = new Set(schema.required ?? []);

  const invoke = useMutation({
    mutationFn: () => {
      const input: Record<string, unknown> = {};
      for (const [key, spec] of fields) {
        const raw = values[key] ?? "";
        if (!raw) continue;
        if (spec.type === "number" || spec.type === "integer") input[key] = Number(raw);
        else if (spec.type === "boolean") input[key] = raw === "true";
        else if (spec.type === "object" || spec.type === "array") {
          try {
            input[key] = JSON.parse(raw);
          } catch {
            input[key] = raw;
          }
        } else input[key] = raw;
      }
      return api<PluginInvocation>(`/api/plugins/instances/${instanceId}/tools/${tool.name}/invoke`, {
        method: "POST",
        body: JSON.stringify({ input }),
      });
    },
    onSuccess: (invocation) => {
      setResult(invocation);
      void qc.invalidateQueries({ queryKey: ["plugin-invocations", instanceId] });
    },
  });

  const missingRequired = [...required].some((key) => !(values[key] ?? "").trim());

  return (
    <div className="overflow-hidden rounded-md border border-border bg-panel">
      <div className="flex items-center gap-1.5 px-2">
        {/* 勾 = 暴不暴露给智能体和工作流。默认关 —— 一个 MCP 端点可能报几十个工具。 */}
        <span className="grid size-7 shrink-0 place-items-center">
          <Checkbox checked={tool.exposed} onCheckedChange={(next) => onToggle(next === true)} aria-label={tool.name} />
        </span>
        <button
          type="button"
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 border-0 bg-transparent py-[9px] text-left"
          onClick={() => setOpen((value) => !value)}
        >
          <Terminal size={14} className="shrink-0" />
          <div className="min-w-0 flex-1 [&_small]:block [&_small]:truncate [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-ui-sm [&_strong]:font-semibold">
            <strong>{tool.label || tool.name}</strong>
            <small>{tool.description}</small>
          </div>
          {tool.read_only && (
            <small className="whitespace-nowrap rounded-full bg-secondary px-1.5 py-px text-ui-2xs text-muted-foreground">
              {t("pluginToolReadOnly")}
            </small>
          )}
          {open ? (
            <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight size={13} className="shrink-0 text-muted-foreground" />
          )}
        </button>
      </div>
      {open && (
        <div className="grid gap-1.5 border-t border-border p-2">
          {fields.map(([key, spec]) => (
            <label
              className="grid gap-1 [&>span]:text-ui-xs [&>span]:text-muted-foreground [&_em]:not-italic [&_em]:text-destructive"
              key={key}
            >
              <span>
                {key}
                {required.has(key) && <em>*</em>}
                {spec.description ? ` — ${spec.description}` : ""}
              </span>
              <Input
                value={values[key] ?? ""}
                placeholder={spec.type ?? "string"}
                onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))}
              />
            </label>
          ))}
          <div className="flex justify-end">
            <Button size="sm" disabled={!runnable || missingRequired} loading={invoke.isPending} onClick={() => invoke.mutate()}>
              <Play size={13} /> {t("runTool")}
            </Button>
          </div>
          {result && <ResultBlock ok={result.status === "succeeded"} body={result.status === "succeeded" ? result.output : result.error ?? result.status} />}
        </div>
      )}
    </div>
  );
});

function InvocationList({ instanceId }: { instanceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const invocations = useQuery({
    queryKey: ["plugin-invocations", instanceId],
    queryFn: () => api<PluginInvocation[]>(`/api/plugins/invocations?instance_id=${instanceId}`),
  });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["plugin-invocations", instanceId] });
  const clear = useMutation({
    mutationFn: () => api(`/api/plugins/invocations?instance_id=${instanceId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/plugins/invocations/${id}`, { method: "DELETE" }),
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
    <div className="overflow-hidden rounded-md border border-border bg-panel">
      <div className="flex items-stretch [&>button:first-child]:min-w-0 [&>button:first-child]:flex-1">
        <button
          type="button"
          className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent px-2 py-[9px] text-left hover:bg-secondary"
          onClick={() => setOpen((value) => !value)}
        >
          {ok ? <CheckCircle2 size={14} className="text-success" /> : <CircleAlert size={14} className="text-destructive" />}
          <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-ui-sm [&_strong]:font-semibold">
            <strong>{invocation.tool_name}</strong>
            <small>{invocation.status}</small>
          </div>
        </button>
        <button
          type="button"
          className="grid w-8 flex-none cursor-pointer place-items-center border-0 bg-transparent text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-destructive"
          aria-label={t("delete")}
          onClick={onDelete}
        >
          <Trash2 size={13} />
        </button>
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
  const full = React.useMemo(() => (typeof body === "string" ? body : JSON.stringify(body, null, 2)), [body]);
  const clipped = full.length > RESULT_RENDER_LIMIT;
  const shown = clipped ? full.slice(0, RESULT_RENDER_LIMIT) : full;
  return (
    <div className="grid gap-1">
      <pre
        className={cn(
          "m-0 max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md px-2 py-1.5 font-mono text-ui-xs leading-[1.5] [word-break:break-word]",
          ok
            ? "border border-[color-mix(in_oklab,var(--success)_30%,var(--border))] bg-[color-mix(in_oklab,var(--success)_8%,var(--background))]"
            : "border border-[color-mix(in_oklab,var(--destructive)_30%,var(--border))] bg-[color-mix(in_oklab,var(--destructive)_7%,var(--background))] text-destructive",
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
