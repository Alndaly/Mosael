import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ChevronDown, ExternalLink, KeyRound, LogIn, LogOut, MoreHorizontal, Pencil, Plus, Power, Trash2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { toast } from "sonner";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { CodeEditor } from "@/components/app/code-editor";
import { ProviderOAuthDialog } from "@/features/settings/ProviderOAuthDialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ProviderModelList } from "@/features/settings/ProviderModelList";
import { ProviderHealth } from "@/features/settings/ProviderHealth";
import { ProviderQuota } from "@/features/settings/ProviderQuota";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";
import { cn } from "@/lib/utils";
import { BulkActionBar, BulkCheckbox, BulkSelectTrigger, useBulkSelection } from "@/components/app/bulkSelection";

type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type VendorPreset = components["schemas"]["VendorPresetOut"];
type ProfileForm = {
  vendor: string;
  name: string;
  /** Adapter-specific settings, keyed by the backend preset's field spec. */
  config: Record<string, string>;
  /** 该档案实际支持的能力(可覆盖 vendor 默认)。生成/分析等按此过滤,避免供应商×模型错配。 */
};

/** 可勾选的能力项(与后端 ALL_CAPABILITY_IDS 对齐;podcast 太小众,表单里不列)。 */

/** 各供应商创建密钥的官方控制台入口(告知用户"去哪拿 key")。外链走系统浏览器。 */
const VENDOR_DOCS: Record<string, string> = {
  alibaba: "https://bailian.console.aliyun.com/?tab=model#/api-key",
  bytedance: "https://console.volcengine.com/ark",
  moonshot: "https://platform.moonshot.cn/console/api-keys",
  minimax: "https://platform.minimaxi.com/user-center/basic-information/interface-key",
  openai: "https://platform.openai.com/api-keys",
  "openai-tts": "https://platform.openai.com/api-keys",
  google: "https://aistudio.google.com/app/apikey",
  kuaishou: "https://klingai.com/",
  "volcano-podcast": "https://console.volcengine.com/speech/service",
  volcano: "https://console.volcengine.com/speech/service",
};

function cleanConfig(config: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(config).map(([key, value]) => [key, (value ?? "").trim()]));
}

/** 溢出菜单里的一行。用 Popover 而不是 DropdownMenu:这个项目没有装后者,
 *  而 Popover 已经处理好了「Dialog 内外的 modal 差异」(见 components/ui/popover)。 */
function MenuItem({
  icon,
  label,
  destructive,
  onSelect,
}: {
  icon: React.ReactNode;
  label: string;
  destructive?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "flex w-full cursor-pointer items-center gap-2 rounded-sm border-0 bg-transparent px-2 py-[6px] text-left text-[12.5px] hover:bg-secondary",
        destructive ? "text-destructive" : "text-foreground",
      )}
      onClick={onSelect}
    >
      <span className="shrink-0 opacity-70">{icon}</span>
      {label}
    </button>
  );
}

export function ProviderProfilesSection({
  capability,
  title,
  description,
}: {
  capability?: string | null;
  title?: string;
  description?: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState<ProviderProfile | null>(null);
  const [removing, setRemoving] = React.useState<ProviderProfile | null>(null);
  // 连接归建它的那个人(见后端 db.models.ProviderProfile),而列表里只会出现自己的 ——
  // 所以这里**没有**按角色分档的必要了:能看到它就说明它是我的,我就改得动。
  // 此前这里按 is_deployment_admin 把连接字段设成只读,那是"连接属于部署"年代的写法,
  // 它让一个普通成员看得见自己的连接却改不了任何一个字段。
  const EMPTY: ProfileForm = { vendor: "moonshot", name: "", config: {} };

  const profiles = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const vendors = useQuery({
    queryKey: ["provider-vendors"],
    queryFn: () => api<VendorPreset[]>("/api/settings/provider-vendors"),
  });
  const refresh = () => {
    // 档案启停/新增/删除都会改变"某能力有哪些模型可选",顶部那几个默认模型下拉读的是
    // capability-models —— 不一起失效就得刷新整页才看得到新模型。
    void qc.invalidateQueries({ queryKey: ["capability-models"] });
    void qc.invalidateQueries({ queryKey: ["provider-defaults"] });
    return qc.invalidateQueries({ queryKey: ["provider-profiles"] });
  };
  /** 某 vendor 的默认能力(新建/换 vendor 时用作能力初值)。 */

  const schema = React.useMemo(() => {
    return z
      .object({
        vendor: z.string(),
        name: z.string().trim().min(1, t("fieldRequired")),
        // 可选字段留空时值是 undefined,z.string() 会在 superRefine 之前就报「expected string」;
        // .catch("") 把缺失/非串值归一成空串,可选字段才真能留空(必填仍由下方 superRefine 校验)。
        config: z.record(z.string(), z.string().catch("")),
      })
      .superRefine((data, ctx) => {
        const preset = (vendors.data ?? []).find((item) => item.vendor === data.vendor);
        for (const spec of preset?.fields ?? []) {
          if (!spec.required) continue;
          if (editing && spec.secret) continue;
          if ((data.config?.[spec.key] ?? "").trim()) continue;
          ctx.addIssue({ code: z.ZodIssueCode.custom, message: t("fieldRequired"), path: ["config", spec.key] });
        }
      });
  }, [editing, t, vendors.data]);
  const form = useForm<ProfileForm>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  const vendor = form.watch("vendor");

  const vendorOptions = React.useMemo(() => {
    const items = vendors.data ?? [];
    return capability ? items.filter((item) => (item.capability_ids ?? []).includes(capability)) : items;
  }, [capability, vendors.data]);
  const visibleProfiles = React.useMemo(() => {
    const items = profiles.data ?? [];
    return capability ? items.filter((profile) => (profile.capability_ids ?? []).includes(capability)) : items;
  }, [capability, profiles.data]);
  const initialVendor = vendorOptions[0]?.vendor ?? "moonshot";

  React.useEffect(() => {
    if (!adding || editing || vendorOptions.some((item) => item.vendor === vendor)) return;
    form.setValue("vendor", initialVendor);
  }, [adding, editing, form, initialVendor, vendor, vendorOptions]);

  // 换 vendor(仅新建时)→ 能力初值重置为该 vendor 的默认;编辑时 vendor 不动、保留档案能力。
  const closeModal = () => {
    setAdding(false);
    setEditing(null);
    form.reset({ ...EMPTY, vendor: initialVendor });
  };
  const openCreate = () => {
    setEditing(null);
    form.reset({ ...EMPTY, vendor: initialVendor });
    setAdding(true);
  };
  const openEdit = (profile: ProviderProfile) => {
    setAdding(false);
    setEditing(profile);
    // 密钥只存掩码,留空表示保持不变
    form.reset({
      vendor: profile.vendor,
      name: profile.name,
      // 编辑时用档案实际生效能力(后端返回 effective:有覆盖用覆盖,否则 vendor 默认)。
      // Secret fields come back only as "…abcd", so prefilling one would submit the mask as
      // the new value. Blank means "keep".
      config: Object.fromEntries(
        (vendors.data?.find((item) => item.vendor === profile.vendor)?.fields ?? []).map((spec) => [
          spec.key,
          spec.secret ? "" : (profile.config ?? {})[spec.key] ?? "",
        ]),
      ),
    });
  };

  const create = useMutation({
    mutationFn: (values: ProfileForm) =>
      api<ProviderProfile>("/api/settings/providers", {
        method: "POST",
        body: JSON.stringify({
          name: values.name.trim(),
          vendor: values.vendor,
          config: cleanConfig(values.config),
        }),
      }),
    onSuccess: () => {
      closeModal();
      void refresh();
    },
  });
  /* 一个弹窗,两件事:**连接**(端点、名字 —— 部署的配置)和**我的密钥**(我自己的)。
     它们走不同的接口、要不同的权限,但对用户是同一件事「配好这个供应商」,所以不该是两个入口。
     密钥字段在这里被拆出来单独 PUT:普通成员改不了连接,但永远配得了自己的密钥。 */
  const update = useMutation({
    mutationFn: async ({ id, values }: { id: string; values: ProfileForm }) => {
      const specs = (vendors.data ?? []).find((v) => v.vendor === values.vendor)?.fields ?? [];
      const secretKeys = new Set(specs.filter((f) => f.secret).map((f) => f.key));
      const config = cleanConfig(values.config);
      const secrets: Record<string, string> = {};
      for (const key of Object.keys(config)) {
        if (secretKeys.has(key)) {
          secrets[key] = config[key];
          delete config[key];
        }
      }
      const apiKeyField = specs.find((f) => f.secret && f.storage === "api_key")?.key;
      const apiKey = apiKeyField ? secrets[apiKeyField] : undefined;
      if (apiKeyField) delete secrets[apiKeyField];
      if (apiKey || Object.keys(secrets).length) {
        await api(`/api/settings/providers/${id}/credential`, {
          method: "PUT",
          body: JSON.stringify({ api_key: apiKey ?? null, secrets }),
        });
      }
      await api<ProviderProfile>(`/api/settings/providers/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: values.name.trim(), config }),
      });
    },
    onSuccess: () => {
      closeModal();
      void refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const submit = form.handleSubmit((values) => {
    if (editing) update.mutate({ id: editing.id, values });
    else create.mutate(values);
  });
  const toggle = useMutation({
    mutationFn: (profile: ProviderProfile) =>
      api<ProviderProfile>(`/api/settings/providers/${profile.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !profile.enabled }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/settings/providers/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  /* 批量:同一批临时试的端点、或换供应商后要整体停掉的一组,逐个点开关会点很久。
     **删除仍然要过确认**——删连接会连带它的模型行和指向它的能力默认,不是可以顺手做的事。 */
  const bulk = useBulkSelection(visibleProfiles, (profile) => profile.id);
  const [bulkDeleting, setBulkDeleting] = React.useState(false);
  const bulkPatch = useMutation({
    mutationFn: async ({ ids, enabled }: { ids: string[]; enabled: boolean }) => {
      await Promise.allSettled(
        ids.map((id) =>
          api(`/api/settings/providers/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
        ),
      );
    },
    onSuccess: () => {
      bulk.clear();
      void refresh();
    },
  });
  const bulkRemove = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.allSettled(ids.map((id) => api(`/api/settings/providers/${id}`, { method: "DELETE" })));
    },
    onSuccess: () => {
      bulk.clear();
      setBulkDeleting(false);
      void refresh();
    },
  });
  const bulkBusy = bulkPatch.isPending || bulkRemove.isPending;

  /** 正在授权的档案。订阅计划没有可填的 Key,授权是它唯一的"配置"动作。 */
  const [authing, setAuthing] = React.useState<ProviderProfile | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const logout = useMutation({
    mutationFn: (id: string) => api(`/api/settings/providers/${id}/oauth`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const isOauth = (profile: ProviderProfile) => profile.auth_type === "oauth";

  const vendorLabel = (value: string) => (vendors.data ?? []).find((item) => item.vendor === value)?.label ?? value;
  const preset = (vendors.data ?? []).find((item) => item.vendor === vendor) ?? null;
  const docsUrl = VENDOR_DOCS[vendor];

  return (
    <SettingsGroup
      title={title ?? t("providerAccountsTitle")}
      description={description ?? t("providerAccountsDesc")}
      actions={
        <div className="flex items-center gap-1.5">
          <BulkSelectTrigger active={bulk.active} onEnter={bulk.enter} disabled={visibleProfiles.length === 0} />
          <Button variant="outline" size="sm" onClick={openCreate}>
            <Plus size={13} /> {t("providerAdd")}
          </Button>
        </div>
      }
    >
      <ModalShell
        open={adding || editing !== null}
        onOpenChange={(next) => !next && closeModal()}
        title={editing ? t("providerEdit") : t("providerAdd")}
      >
        <Form {...form}>
          <form className="grid gap-2.5 [&_textarea]:resize-y [&_textarea]:rounded [&_textarea]:border [&_textarea]:border-border [&_textarea]:bg-field [&_textarea]:p-1.5 [&_textarea]:text-[12.5px] [&_textarea]:text-foreground [&_textarea:focus-visible]:border-primary [&_textarea:focus-visible]:outline-none" onSubmit={submit} noValidate>
            <FormField
              control={form.control}
              name="vendor"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("providerVendorLabel")}</FormLabel>
                  {editing ? (
                    // 供应商类型是解析主键、编辑时不可改;只读显示,避免非预设 vendor 的空下拉
                    <Input value={vendorLabel(field.value)} disabled readOnly />
                  ) : (
                    <FormControl>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {vendorOptions.map((item) => (
                            <SelectItem key={item.vendor} value={item.vendor}>
                              {item.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormControl>
                  )}
                  {preset?.capabilities && (
                    <FormDescription className="mt-0.5 leading-[1.4] text-muted-foreground">{preset.capabilities}</FormDescription>
                  )}
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t("providerNameLabel")}</FormLabel>
                  <FormControl>
                    <Input placeholder={t("providerName")} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {preset?.auth?.includes("oauth") && (preset?.fields ?? []).length === 0 && (
              <p className="m-0 rounded-md border border-border bg-panel p-2 text-[11.5px] leading-[1.5] text-muted-foreground">
                {t("providerOauthHint")}
                {!editing && ` ${t("providerOauthSaveFirst")}`}
              </p>
            )}
            {(preset?.fields ?? []).map((spec) => (
              <FormField
                key={spec.key}
                control={form.control}
                name={`config.${spec.key}` as const}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="flex items-center gap-2">
                      {spec.label}
                      {spec.storage === "api_key" && docsUrl && (
                        <a className="ml-auto inline-flex items-center gap-[3px] text-[11px] font-medium text-primary no-underline hover:underline" href={docsUrl} target="_blank" rel="noreferrer noopener">
                          {t("providerGetKey")}
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </FormLabel>
                    <FormControl>
                      {/* 密的字段是**我的**,谁都能改;其余是连接的配置,只有部署管理员改得动。 */}
                      {spec.multiline ? (
                        <CodeEditor
                          language="json"
                          value={field.value ?? ""}
                          onChange={field.onChange}
                          onBlur={field.onBlur}
                          placeholder={spec.default || ""}
                          minHeight={140}
                          maxHeight={320}
                        />
                      ) : (
                        <Input
                          type={spec.secret ? "password" : "text"}
                          placeholder={spec.secret && editing ? t("providerKeyKeepPlaceholder") : spec.default || ""}
                          {...field}
                          value={field.value ?? ""}
                        />
                      )}
                    </FormControl>
                    {(spec.hint || spec.default) && (
                      <FormDescription>
                        {spec.hint || t("providerFieldDefault").replace("{value}", spec.default)}
                      </FormDescription>
                    )}
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
            {/* 「支持能力」这一栏已经删掉。它编辑的是 ProviderProfile.capability_ids —— 那个字段在
                供应商⇄模型重构里就没了(能力挂在模型行上:同一个端点既可能有对话模型也可能有生图
                模型,挂在连接上就只能二选一)。更新路由一直显式忽略它,于是这一栏勾了、存了、
                什么都没发生。能力现在在每个模型/工作流自己的设置弹窗里改。 */}
            <div className="mt-1 flex justify-end gap-1.5">
              <Button type="button" variant="outline" size="sm" onClick={closeModal}>
                {t("cancel")}
              </Button>
              <Button type="submit" size="sm" disabled={editing ? update.isPending : create.isPending}>
                {editing ? (
                  t("save")
                ) : (
                  <>
                    <Plus size={13} /> {t("providerAdd")}
                  </>
                )}
              </Button>
            </div>
          </form>
        </Form>
      </ModalShell>

      <ConfirmDialog
        open={removing !== null}
        title={t("providerDeleteConnection")}
        body={t("providerDeleteConnectionBody")
          .replace("{name}", removing?.name ?? "")
          .replace("{caps}", (removing?.capability_ids ?? []).map((id) => t(`capability_${id}` as never)).join("、") || "—")}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (removing) remove.mutate(removing.id);
          setRemoving(null);
        }}
      />
      <ConfirmDialog
        open={bulkDeleting}
        title={t("bulkDeleteConfirm").replace("{n}", String(bulk.count))}
        body={t("bulkDeleteConfirmBody").replace("{n}", String(bulk.count))}
        onCancel={() => setBulkDeleting(false)}
        onConfirm={() => bulkRemove.mutate(bulk.selectedIds)}
      />

      <SettingsBlock>
        <div className="grid gap-1.5">
          <BulkActionBar active={bulk.active} count={bulk.count} allSelected={bulk.allSelected} onToggleAll={bulk.toggleAll} onExit={bulk.exit}>
            <Button variant="outline" size="sm" disabled={bulkBusy} loading={bulkPatch.isPending} onClick={() => bulkPatch.mutate({ ids: bulk.selectedIds, enabled: true })}>
              {t("bulkEnable")}
            </Button>
            <Button variant="outline" size="sm" disabled={bulkBusy} loading={bulkPatch.isPending} onClick={() => bulkPatch.mutate({ ids: bulk.selectedIds, enabled: false })}>
              {t("bulkDisable")}
            </Button>
            <Button variant="outline" size="sm" disabled={bulkBusy} onClick={() => setBulkDeleting(true)}>
              <Trash2 size={12} /> {t("bulkDelete")}
            </Button>
          </BulkActionBar>
          {visibleProfiles.map((profile) => (
            <div
              className={cn(
                "grid items-center gap-2 rounded-md border border-border bg-panel px-2 py-1.5",
                bulk.active ? "grid-cols-[auto_28px_minmax(0,1fr)_auto_auto]" : "grid-cols-[28px_minmax(0,1fr)_auto_auto]",
                !profile.enabled && "opacity-55",
                bulk.isSelected(profile.id) && "border-primary/45 bg-[color-mix(in_srgb,var(--primary)_5%,var(--panel))] opacity-100",
              )}
              key={profile.id}
            >
              {bulk.active && (
                <BulkCheckbox
                  checked={bulk.isSelected(profile.id)}
                  onToggle={(event) => bulk.toggle(profile.id, event)}
                  label={t("bulkSelectRow")}
                />
              )}
              <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground">
                <KeyRound size={13} />
              </span>
              <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[13px] [&_strong]:font-semibold">
                <strong>{profile.name}</strong>
                <small>
                  {vendorLabel(profile.vendor)}
                  {isOauth(profile) ? (
                    <>
                      {" · "}
                      {profile.oauth_linked ? (
                        profile.oauth_expired ? (
                          // 走到这里说明后端已经替它刷过且没刷动(见 _auto_refresh_expired)——
                          // 单纯的"过期"不会到用户面前,所以这一行现在确实需要人来处理,
                          // 用警告色说出来。
                          <span className="text-destructive">{t("providerOauthExpired")}</span>
                        ) : (
                          t("providerOauthLinked")
                        )
                      ) : (
                        t("providerOauthUnlinked")
                      )}
                    </>
                  ) : profile.key_hint ? (
                    ` · ${profile.key_hint}`
                  ) : profile.needs_key ? (
                    <> · <span className="text-destructive">{t("providerNoKeyOfMine")}</span></>
                  ) : (
                    /* 免密钥的(本机 ComfyUI):它压根没有密钥可配,一行红字只会让人去找一个
                       不存在的输入框。判据由后端给(needs_key),不在这里按 vendor 名字硬编 ——
                       下一个免密钥的 vendor 加进来时,硬编的那份没有任何东西会提醒你。 */
                    <> · {t("providerKeyless")}</>
                  )}
                  {profile.base_url ? ` · ${profile.base_url}` : ""}
                  {/* 在线状态贴在地址后面:它说的正是"这个地址通不通"。 */}
                  <ProviderHealth profileId={profile.id} className="ml-1.5 align-middle" />
                </small>
              </div>
              {!profile.enabled && <Badge variant="outline">{t("providerDisabled")}</Badge>}
              <div className="flex items-center gap-1">
                {/* 常用的三个留在行内:展开模型、查额度、启停。授权/编辑/删除进溢出菜单 ——
                    订阅档案原本七个图标挤成一排,每个都同等分量,反而哪个都不显眼。 */}
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("modelListTitle")}
                  title={t("modelListTitle")}
                  onClick={() =>
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(profile.id)) next.delete(profile.id);
                      else next.add(profile.id);
                      return next;
                    })
                  }
                >
                  <ChevronDown size={13} className={cn("transition-transform", expanded.has(profile.id) && "rotate-180")} />
                </Button>
                {/* 只对真有额度接口的供应商出现。没有端点的不摆这个钮 —— 亮着却只能回一句
                    "不支持",等于摆了个做不到的操作。 */}
                {profile.oauth_linked && profile.quota_supported && <ProviderQuota profileId={profile.id} />}
                <Button variant="ghost" size="icon" loading={toggle.isPending && toggle.variables?.id === profile.id} onClick={() => toggle.mutate(profile)} aria-label="toggle">
                  <Power size={13} />
                </Button>
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={t("more")} title={t("more")}>
                      <MoreHorizontal size={13} />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="w-[168px] p-1">
                    {isOauth(profile) && (
                      <MenuItem
                        icon={<LogIn size={13} />}
                        label={profile.oauth_linked ? t("providerOauthRelogin") : t("providerOauthLogin")}
                        onSelect={() => setAuthing(profile)}
                      />
                    )}
                    {isOauth(profile) && profile.oauth_linked && (
                      <MenuItem
                        icon={<LogOut size={13} />}
                        label={t("providerOauthLogout")}
                        onSelect={() => logout.mutate(profile.id)}
                      />
                    )}
                    <MenuItem icon={<Pencil size={13} />} label={t("providerEdit")} onSelect={() => openEdit(profile)} />
                    {/* 删的是**整条连接**,不是"从这个能力里移除" —— 一条连接可以同时供
                        对话与生图(能力在模型行上)。在能力分区里点「删除」很容易被读成后者,
                        所以这里点名它会连带什么消失,并且要过一次确认。 */}
                    <MenuItem
                      icon={<Trash2 size={13} />}
                      label={t("providerDeleteConnection")}
                      destructive
                      onSelect={() => setRemoving(profile)}
                    />
                  </PopoverContent>
                </Popover>
              </div>
              {/* 展开区整行独占:模型行本身就是"名字 + 能力 + 开关 + 两个按钮",
                  挤进那一列会窄到读不出任何东西。 */}
              {expanded.has(profile.id) && (
                <div className="col-span-full border-t border-border pt-2">
                  <ProviderModelList profileId={profile.id} vendor={profile.vendor} />
                </div>
              )}
            </div>
          ))}
          {profiles.data && visibleProfiles.length === 0 && (
            <p className="m-0 text-xs text-muted-foreground">{capability ? t("providerNoCapabilityProfiles") : t("providerNoProfiles")}</p>
          )}
        </div>
      </SettingsBlock>

      {authing && (
        <ProviderOAuthDialog
          profileId={authing.id}
          profileName={authing.name}
          open
          onOpenChange={(next) => !next && setAuthing(null)}
        />
      )}
    </SettingsGroup>
  );
}
