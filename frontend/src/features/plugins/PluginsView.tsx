import { CollectionDetail, COLLECTION_DETAIL_PAGE, COLLECTION_DETAIL_HEADING, DETAIL_INDEX_ITEM, DETAIL_INDEX_SELECTED, DETAIL_INDEX_TEXT } from "@/components/layout/CollectionDetail";
import { PageHeading } from "@/components/layout/StudioPage";
import React from "react";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Copy, ExternalLink, KeyRound, Lock, Play, Plug, Plus, RefreshCcw, Store, Terminal, Trash2 } from "lucide-react";

import {
  api,
  type PluginField,
  type PluginInstance,
  type PluginInvocation,
  type PluginPackage,
  type PluginPermissionGrant,
} from "@/api/client";
import { toast } from "sonner";
import { useI18n, usePreferences } from "@/app/preferences";
import { docsUrl } from "@/lib/deepLink";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/layout/EmptyState";
import { PluginMarketDialog } from "@/features/plugins/PluginMarket";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Skeleton } from "@/components/ui/skeleton";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { usePersistentSelection } from "@/lib/usePersistentTab";
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
export function PluginsView({ workspaceId }: { workspaceId: string }) {
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
  const empty = packages.isSuccess && list.length === 0;
  const selected = list.find((item) => item.id === selectedId) ?? list[0] ?? null;


  const heading = <PageHeading className={COLLECTION_DETAIL_HEADING} title={t("pluginsTitle")} description={t("studioPluginsDesc")} count={packages.data?.length} actions={<><ScanButton pending={scan.isPending} onScan={() => scan.mutate()} /><Button onClick={() => setMarketOpen(true)}><Store />{t("studioBrowsePlugins")}</Button></>} />;
  if (empty) return <div className={COLLECTION_DETAIL_PAGE}>
    {heading}<div className="flex min-h-0 flex-1 overflow-y-auto"><EmptyState icon={<Plug size={28} />} title={t("pluginsTitle")} body={t("noPluginsGuide").replace("{dir}", pluginsDir.data?.path ?? "")} action={<Button onClick={() => setMarketOpen(true)}><Store />{t("studioBrowsePlugins")}</Button>} /></div>
    <PluginMarketDialog open={marketOpen} onOpenChange={setMarketOpen} onInstalled={() => invalidatePlugins(qc)} />
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
              const live = (item.instances ?? []).filter((i) => i.enabled).length;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={cn(DETAIL_INDEX_ITEM, selected?.id === item.id && DETAIL_INDEX_SELECTED)}
                  aria-current={selected?.id === item.id ? "true" : undefined}
                  onClick={() => setSelectedId(item.id)}
                >
                  <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", live > 0 && "bg-success")} />
                  <span className={DETAIL_INDEX_TEXT}>
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
      </>}>
          {selected ? (
            <PackageDetail key={selected.id} pkg={selected} workspaceId={workspaceId} />
          ) : (
            <EmptyState icon={<Plug size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
      </CollectionDetail>
      <PluginMarketDialog open={marketOpen} onOpenChange={setMarketOpen} onInstalled={() => invalidatePlugins(qc)} />
    </div>
  );
}

function invalidatePlugins(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["plugins"] });
  void qc.invalidateQueries({ queryKey: ["plugin-tools"] });
  void qc.invalidateQueries({ queryKey: ["workflow-node-types"] });
}

/** 扫描按钮:pending 时图标转起来、文案改成「扫描中」—— 以前只是 disabled,点下去像没点上。 */
function ScanButton({ pending, onScan }: { pending: boolean; onScan: () => void }) {
  const t = useI18n();
  return <Button variant="outline" loading={pending} onClick={onScan}>
    <RefreshCcw />{pending ? t("scanningPlugins") : t("scanPlugins")}
  </Button>;
}

function PackageDetail({ pkg, workspaceId }: { pkg: PluginPackage; workspaceId: string }) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [confirmUninstall, setConfirmUninstall] = React.useState(false);
  const [addOpen, setAddOpen] = React.useState(false);
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
      // 建好就关窗、清草稿 —— 留着开会让人以为没成功,而新连接已经出现在下面的列表里了。
      setAddOpen(false);
      setDraft({});
      invalidatePlugins(qc);
    },
  });

  const canAdd = pkg.multiple || (pkg.instances ?? []).length === 0;

  const instances = pkg.instances ?? [];
  const live = instances.filter((one) => one.enabled).length;

  return (
    <div className="grid w-full min-w-0 content-start gap-6">
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
      <header className="grid gap-5 border-b border-divider pb-5">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 truncate text-xl font-semibold tracking-tight text-foreground">{pkg.name}</h2>
          <span className="flex shrink-0 items-center gap-1">
            {/* 「文档」指向 **Mosael 自己的插件文档**,不是插件作者的站点。
                这一页上的问题是"连接是什么、凭据填哪儿、权限为什么要授、工具为什么默认不开"
                —— 那些是本应用的概念,只有我们说得清;把人送到百度网盘的 API 文档上,
                他要找的东西那儿一个字都没有。
                插件作者的站点仍然给,但**标明是它自己的主页**(声明了才画:一个点不开的
                按钮比没有更糟)。 */}
            <Button variant="ghost" size="default" className="text-muted-foreground" asChild>
              <a href={docsUrl("guides/plugins", locale)} target="_blank" rel="noreferrer noopener">
                <BookOpen size={13} /> {t("pluginDocs")}
              </a>
            </Button>
            {pkg.homepage && (
              <Button variant="ghost" size="default" className="text-muted-foreground" asChild>
                <a href={pkg.homepage} target="_blank" rel="noreferrer noopener">
                  <ExternalLink size={13} /> {t("pluginHomepage")}
                </a>
              </Button>
            )}
            <Button
              variant="ghost"
              size="default"
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
        <ConnectionCard key={instance.id} pkg={pkg} instance={instance} workspaceId={workspaceId} />
      ))}

      {/* **一个按钮进弹窗,不是常驻的内联表单。** 内联那版有两个毛病:已经有连接时它仍然
          占着版面,而"再建一个"是低频操作;而且一个都没有时,它和空状态在说同一件事 ——
          后者的说明几乎逐字重复前者("同一个插件可以接多个,比如每个平台一个")。 */}
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
      ) : canAdd ? (
        <div className="flex justify-start">
          <Button variant="secondary" size="sm" onClick={() => setAddOpen(true)}>
            <Plus size={13} /> {t("pluginNewConnection")}
          </Button>
        </div>
      ) : null}

      {canAdd && (
        <NewConnectionDialog
          pkg={pkg}
          open={addOpen}
          onOpenChange={setAddOpen}
          draft={draft}
          setDraft={setDraft}
          pending={createInstance.isPending}
          onCreate={() => createInstance.mutate()}
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
 */
function NewConnectionDialog({
  pkg, open, onOpenChange, draft, setDraft, pending, onCreate,
}: {
  pkg: PluginPackage;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  draft: Record<string, string>;
  setDraft: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  pending: boolean;
  onCreate: () => void;
}) {
  const t = useI18n();
  const fields = pkg.config_fields ?? [];
  // 没有配置项时还要分一次:有凭据的插件说"不需要配置"是错的 —— AppKey 这些确实要填,
  // 只是填在**建好之后的连接上**(凭据挂在连接上,不是插件上)。
  const hint = fields.length
    ? t("pluginNewConnectionDesc")
    : (pkg.credential_fields ?? []).length
      ? t("pluginNewConnectionCreds")
      : t("pluginNewConnectionSimple");
  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("pluginNewConnection")}
      className="w-[420px]"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={pending} onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
          <Button loading={pending} onClick={onCreate}><Plus size={13} /> {t("pluginAddConnection")}</Button>
        </div>
      }
    >
      <div className="grid gap-4">
        <p className="m-0 text-ui-sm leading-[1.6] text-muted-foreground">{hint}</p>
        {fields.map((field) => (
          <label key={field.key} className="grid gap-1.5">
            <span className="text-ui-sm font-medium text-foreground">{field.label}</span>
            <FieldInput
              field={field}
              value={draft[field.key] ?? field.default}
              onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}
            />
            {/* 清单里的 help 此前一个字都没显示。Blender 插件那条正是用户会撞到的限制:
                「互通要求 Blender 与后端在同一台电脑」。 */}
            {field.help && <small className="text-ui-xs leading-[1.5] text-muted-foreground">{field.help}</small>}
          </label>
        ))}
      </div>
    </ModalShell>
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
}: {
  field: PluginField;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const t = useI18n();
  if (field.type === "enum") {
    const options = (field.options as { value: string; label: string }[]) ?? [];
    if (options.length <= 1) {
      const only = options[0];
      return (
        <p className={cn("m-0 flex h-10 min-w-0 items-center gap-1.5 text-ui-sm text-muted-foreground", className)}>
          <Lock size={12} className="shrink-0" />
          <span className="truncate">{only?.label ?? value}</span>
        </p>
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
  return (
    <Input
      className={className}
      type={field.secret ? "password" : field.type === "number" ? "number" : "text"}
      value={value}
      placeholder={field.label}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function ConnectionCard({ pkg, instance, workspaceId }: { pkg: PluginPackage; instance: PluginInstance; workspaceId: string }) {
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
      className="[&_[data-slot=settings-group-title]]:text-ui-md [&_[data-slot=settings-group-description]]:text-ui-sm"
      title={!pkg.multiple && instance.name === pkg.name ? t("pluginConnectionSettings") : instance.name}
      description={
        instance.blocked_reason
          ? instance.blocked_reason
          : t("pluginExposedCount").replace("{n}", String(exposedCount)).replace("{total}", String((instance.tools ?? []).length))
      }
      actions={
        <div className="flex items-center gap-2">
          <label className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground">
            <span>{instance.enabled ? t("pluginOn") : t("pluginOff")}</span>
            <Switch checked={instance.enabled} onCheckedChange={(enabled) => patch.mutate({ enabled })} />
          </label>
          {pkg.kind === "mcp" && (
            <Button variant="outline" size="default" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              <RefreshCcw size={13} />
              {t("pluginRefreshTools")}
            </Button>
          )}
          <Button
            variant="outline"
            size="default"
            className="px-3 text-muted-foreground hover:text-destructive"
            aria-label={t("pluginDeleteConnectionTitle").replace("{name}", instance.name)}
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

      {(pkg.credential_fields ?? []).length > 0 && (
        <CredentialRows instanceId={instance.id} oauth={Boolean(pkg.oauth)} />
      )}

      {(grants.data ?? []).map((grant) => (
        <SettingsRow key={grant.permission} label={grant.permission} description={t("permissionRowDesc")}>
          <label className="inline-flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border px-3 text-ui-sm text-muted-foreground">
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
        workspaceId={workspaceId}
        tools={instance.tools ?? []}
        blockedReason={instance.blocked_reason ?? ""}
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
  workspaceId,
  tools,
  blockedReason,
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
                // 传**理由**而不是布尔:一个灰着的按钮不说明自己为什么灰,等于没有反馈。
                blockedReason={blockedReason || (tool.exposed ? "" : t("pluginToolNotExposed"))}
                onToggle={(exposed) => onToggle({ [tool.name]: exposed })}
              />
            ))}
          </div>
        </>
      )}
    </SettingsBlock>
  );
}


/**
 * 「去授权」:替用户走完 OAuth 里那段机械的部分。
 *
 * 注册应用拿 AppKey/SecretKey 是他和开放平台之间的事,替代不了。这里替代的是后面那一段 ——
 * 拼授权链接、拿 code 换令牌、把 refresh_token 抄进表单。每一步抄错换回来的都是一句
 * `invalid_client` 之类的英文报错,看不出错在哪一格。
 *
 * **为什么还要粘贴一次 code。** 回调不走 mosael://(自定义协议是外部输入面,任何网页都能
 * 触发它),也不在本机开监听端口(重定向地址要在对方控制台预先登记,而后端端口会变)。
 * 详见 backend/app/domain/plugins/oauth.py 的文件头。多一次粘贴,换这条路上没有可伪造的输入。
 */
function PluginOAuth({ instanceId, save }: { instanceId: string; save?: React.ReactNode }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [url, setUrl] = React.useState("");
  const [code, setCode] = React.useState("");

  const begin = useMutation({
    mutationFn: () => api<{ authorize_url: string }>(`/api/plugins/instances/${instanceId}/oauth`),
    onSuccess: (data) => {
      setUrl(data.authorize_url);
      // 直接开出去 —— 主进程把 http(s) 交给系统浏览器(见 electron/main 的 setWindowOpenHandler)。
      window.open(data.authorize_url, "_blank", "noreferrer");
    },
    // 「先填 AppKey」这类原因由后端说,原样转出来:换成"授权失败"等于把唯一有用的信息扔掉。
    onError: (error: Error) => toast.error(error.message),
  });

  const finish = useMutation({
    mutationFn: () =>
      api(`/api/plugins/instances/${instanceId}/oauth`, { method: "POST", body: JSON.stringify({ code }) }),
    onSuccess: () => {
      setUrl("");
      setCode("");
      toast.success(t("pluginOauthDone"));
      void qc.invalidateQueries({ queryKey: ["plugin-credentials", instanceId] });
      invalidatePlugins(qc);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <>
      <GroupActions hint={t("pluginOauthHint")}>
        <Button size="sm" variant="outline" loading={begin.isPending} onClick={() => begin.mutate()}>
          <ExternalLink size={13} /> {t("pluginOauthStart")}
        </Button>
        {save}
      </GroupActions>
      {url && (
        <div className="px-0.5 pb-3 !border-t-0">
          {/* 链接留着:弹窗拦截、或者他想换个浏览器登录时,总得有个能点的东西。 */}
          <div className="grid gap-1.5 rounded-md border border-border bg-panel p-2.5">
          <a
            className="inline-flex w-fit items-center gap-1 text-ui-xs font-medium text-primary no-underline hover:underline"
            href={url}
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("pluginOauthOpenLink")}
            <ExternalLink size={11} />
          </a>
          <div className="flex items-center gap-1.5">
            <Input
              className="min-w-0 flex-1"
              value={code}
              placeholder={t("pluginOauthCodePlaceholder")}
              onChange={(event) => setCode(event.target.value)}
            />
            <Button size="sm" disabled={!code.trim()} loading={finish.isPending} onClick={() => finish.mutate()}>
              <KeyRound size={13} /> {t("pluginOauthExchange")}
            </Button>
            </div>
          </div>
        </div>
      )}
    </>
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
function GroupActions({ hint, children }: { hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 px-0.5 py-3 !border-t-0">
      {/* 说明文字挤走按钮的话按钮会掉行 —— min-w-0 + flex-1 让它先缩。 */}
      {hint && <small className="min-w-0 flex-1 text-ui-sm leading-[1.5] text-muted-foreground">{hint}</small>}
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  );
}

//: 导出**只为测试**。这两个组件里各有一处靠肉眼才发现的毛病(两个动作叠成两块、
//: 灰按钮不说明理由),而它们都是结构性的 —— 结构该由测试盯着,不该由下一次截图盯着。
export function CredentialRows({ instanceId, oauth }: { instanceId: string; oauth: boolean }) {
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

  // 整组一次提交,不逐格失焦即存:密钥输错一个字符和输对长得一模一样,而逐格自动保存会让
  // "改了一半"和"改完了"在后端无法区分 —— 改到一半正好等于一条连不上的连接。一个显式的
  // 保存按钮同时也是"现在去重连试试"的时机。**它是一个,不是每行一个**:显示条件
  // (`draft` 非空)是整组的,画在 map 里的话改任何一格每行都会长出一个"保存"。
  const dirty = Object.keys(draft).length > 0;
  const saveButton = (
    <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
      <KeyRound size={13} /> {t("pluginCredentialsSave")}
    </Button>
  );

  return (
    <>
      {(credentials.data ?? []).map((item) => (
        <SettingsRow
          key={item.key}
          label={item.label}
          description={item.help || (item.filled ? t("pluginCredentialFilled") : t("pluginCredentialEmpty"))}
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
      {/* 保存和「去授权」是**同一组凭据上的两个动作**,所以排在同一行里,而不是各自
          占一块上下叠着 —— 叠起来时两颗按钮贴得极近、一颗有说明文字一颗没有,看着像
          两件互不相干的事。主动作(保存)在最右,和全应用一致。 */}
      {oauth ? (
        <PluginOAuth instanceId={instanceId} save={dirty ? saveButton : null} />
      ) : (
        dirty && <GroupActions>{saveButton}</GroupActions>
      )}
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
export const ToolRow = React.memo(function ToolRow({
  instanceId,
  workspaceId,
  tool,
  blockedReason,
  onToggle,
}: {
  instanceId: string;
  workspaceId: string;
  tool: ToolState;
  /** 为什么这个工具现在跑不了。空串 = 跑得了。 */
  blockedReason: string;
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
        body: JSON.stringify({ input, workspace_id: workspaceId }),
      });
    },
    onSuccess: (invocation) => {
      setResult(invocation);
      void qc.invalidateQueries({ queryKey: ["plugin-invocations", instanceId] });
      if (invocation.status === "succeeded" && invocation.output.asset_id) {
        void qc.invalidateQueries({ queryKey: ["assets", workspaceId] });
      }
    },
  });

  const missingRequired = [...required].some((key) => !(values[key] ?? "").trim());

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-panel">
      <div className="flex items-center gap-3 px-4">
        {/* 勾 = 暴不暴露给智能体和工作流。默认关 —— 一个 MCP 端点可能报几十个工具。 */}
        <span className="grid size-7 shrink-0 place-items-center">
          <Checkbox checked={tool.exposed} onCheckedChange={(next) => onToggle(next === true)} aria-label={tool.name} />
        </span>
        <button
          type="button"
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 border-0 bg-transparent py-4 text-left"
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
        <div className="grid gap-5 border-t border-divider bg-panel-subtle/40 p-5">
          {fields.map(([key, spec]) => (
            <label
              className="grid gap-2 [&>span]:text-ui-sm [&>span]:font-medium [&>span]:text-foreground [&_em]:not-italic [&_em]:text-destructive"
              key={key}
            >
              <span>
                {key}
                {required.has(key) && <em>*</em>}
                {spec.description ? ` — ${spec.description}` : ""}
              </span>
              {spec.type === "boolean" ? <Select value={values[key] || "__default__"} onValueChange={(value) => setValues(current => ({ ...current, [key]: value === "__default__" ? "" : value }))}>
                <SelectTrigger aria-label={key}><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="__default__">{t("studioBooleanDefault")}</SelectItem><SelectItem value="true">{t("studioBooleanTrue")}</SelectItem><SelectItem value="false">{t("studioBooleanFalse")}</SelectItem></SelectContent>
              </Select> : spec.type === "object" || spec.type === "array" ? <Textarea aria-label={key} rows={4} className="font-mono" value={values[key] ?? ""} placeholder={spec.type === "array" ? "[]" : "{}"} onChange={event => setValues(current => ({ ...current, [key]: event.target.value }))} /> : <Input
                aria-label={key}
                type={spec.type === "number" || spec.type === "integer" ? "number" : "text"}
                step={spec.type === "integer" ? 1 : "any"}
                value={values[key] ?? ""}
                placeholder={spec.type ?? "string"}
                onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))}
              />}
            </label>
          ))}
          {/* **把理由摆在按钮旁边。** 「未启用」这句话本来只写在整组的标题下,而工具行
              可能在它下面好几百像素处 —— 用户看到的就只是一个灰着的按钮,试不出所以然。
              缺必填参数同理:不说的话,他会以为是插件坏了。 */}
          <div className="flex items-center justify-end gap-2">
            {(blockedReason || missingRequired) && (
              <small className="min-w-0 truncate text-ui-xs text-muted-foreground">
                {blockedReason || t("pluginToolMissingRequired")}
              </small>
            )}
            <Button
              size="sm"
              disabled={Boolean(blockedReason) || missingRequired}
              loading={invoke.isPending}
              onClick={() => invoke.mutate()}
            >
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
    <div className="overflow-hidden rounded-lg border border-border bg-panel">
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
