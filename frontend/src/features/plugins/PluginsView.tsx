import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Play, Plug, RefreshCcw, Terminal, Trash2 } from "lucide-react";

import { api, type Plugin, type PluginInvocation, type PluginPermissionGrant, type PluginTool } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { SettingsBlock, SettingsGroup, SettingsRow } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

/**
 * 插件页 = 主从布局(VS Code 扩展页形态):左侧插件列表,右侧选中
 * 插件的完整详情 — 概览 / 权限 / 工具试运行 / 调用历史。视觉语言与
 * 设置页共用同一套 SettingsGroup/Row 组件。
 */
export function PluginsView() {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const plugins = useQuery({
    queryKey: ["plugins"],
    queryFn: () => api<Plugin[]>("/api/plugins"),
  });
  const scanPlugins = useMutation({
    mutationFn: () => api<Plugin[]>("/api/plugins/scan", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plugins"] });
      qc.invalidateQueries({ queryKey: ["plugin-permissions"] });
      qc.invalidateQueries({ queryKey: ["plugin-tools"] });
    },
  });

  const selected =
    (plugins.data ?? []).find((plugin) => plugin.id === selectedId) ?? (plugins.data ?? [])[0] ?? null;

  // 没有任何插件:整页一个居中空状态(扫描是唯一动作),不摆空骨架。
  if (plugins.isSuccess && (plugins.data ?? []).length === 0) {
    return (
      <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
        <EmptyState
          icon={<Plug size={22} />}
          title={t("noPlugins")}
          body={t("noPluginsGuide")}
          action={
            <Button disabled={scanPlugins.isPending} onClick={() => scanPlugins.mutate()}>
              <RefreshCcw size={15} /> {t("scanPlugins")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0">
      <div className="grid min-h-0 flex-1 grid-cols-[260px_minmax(0,1fr)] gap-2 max-[880px]:grid-cols-[minmax(0,1fr)] max-[880px]:grid-rows-[auto_minmax(0,1fr)]">
        <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[880px]:flex max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:px-1.5 max-[880px]:py-[5px] max-[880px]:[&>div:first-child]:contents">
          <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
            <h2>{t("installed")}</h2>
            <Button
              variant="outline"
              size="sm"
              disabled={scanPlugins.isPending}
              onClick={() => scanPlugins.mutate()}
            >
              <RefreshCcw size={13} /> {t("scanPlugins")}
            </Button>
          </div>
          <div className="grid content-start gap-1 overflow-y-auto p-1.5 [&:has(>.empty-inline:only-child)]:content-stretch max-[880px]:order-1 max-[880px]:flex max-[880px]:min-w-0 max-[880px]:flex-1 max-[880px]:items-center max-[880px]:gap-1.5 max-[880px]:overflow-x-auto max-[880px]:p-0">
            {(plugins.data ?? []).map((plugin) => (
              <button
                key={plugin.id}
                type="button"
                className={cn("flex cursor-pointer items-center gap-[9px] rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted max-[880px]:shrink-0 max-[880px]:py-1", selected?.id === plugin.id && "bg-accent hover:bg-accent")}
                onClick={() => setSelectedId(plugin.id)}
              >
                <span className={cn("h-[7px] w-[7px] shrink-0 rounded-full bg-border-strong", plugin.enabled && "bg-[#22c55e]")} />
                <span className="min-w-0 [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:truncate [&_strong]:text-[12.5px] [&_strong]:font-semibold max-[880px]:[&_small]:hidden">
                  <strong>{plugin.name}</strong>
                  <small>v{plugin.version}</small>
                </span>
              </button>
            ))}
          </div>
        </aside>
        <div className="grid min-w-0 overflow-y-auto">
          {selected ? (
            // Keyed so switching plugin remounts: ToolCard is keyed by tool NAME, so without
            // this the next plugin's identically-named tool inherited the previous one's
            // typed arguments and output.
            <PluginDetail key={selected.id} plugin={selected} />
          ) : (
            <EmptyState icon={<Plug size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>
    </div>
  );
}

function PluginDetail({ plugin }: { plugin: Plugin }) {
  const t = useI18n();
  const qc = useQueryClient();

  const grants = useQuery({
    queryKey: ["plugin-permissions", plugin.id],
    queryFn: () => api<PluginPermissionGrant[]>(`/api/plugins/${plugin.id}/permissions`),
  });
  const enabledTools = useQuery({
    queryKey: ["plugin-tools"],
    queryFn: () => api<PluginTool[]>("/api/plugins/tools"),
  });
  const invocations = useQuery({
    queryKey: ["plugin-invocations", plugin.id],
    queryFn: () => api<PluginInvocation[]>(`/api/plugins/invocations?plugin_id=${plugin.id}`),
  });

  const togglePlugin = useMutation({
    mutationFn: (enabled: boolean) =>
      api<Plugin>(`/api/plugins/${plugin.id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plugins"] });
      void qc.invalidateQueries({ queryKey: ["plugin-tools"] });
    },
  });
  const setGrant = useMutation({
    mutationFn: ({ permission, granted }: { permission: string; granted: boolean }) =>
      api<PluginPermissionGrant[]>(`/api/plugins/${plugin.id}/permissions`, {
        method: "PATCH",
        body: JSON.stringify({ grants: { [permission]: granted } }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plugin-permissions", plugin.id] });
      void qc.invalidateQueries({ queryKey: ["plugin-tools"] });
    },
  });
  const invalidateInvocations = () => qc.invalidateQueries({ queryKey: ["plugin-invocations", plugin.id] });
  const deleteInvocation = useMutation({
    mutationFn: (id: string) => api(`/api/plugins/invocations/${id}`, { method: "DELETE" }),
    onSuccess: invalidateInvocations,
  });
  const clearInvocations = useMutation({
    mutationFn: () => api(`/api/plugins/invocations?plugin_id=${plugin.id}`, { method: "DELETE" }),
    onSuccess: invalidateInvocations,
  });

  const manifestTools = ((plugin.manifest.tools as PluginToolManifest[] | undefined) ?? []).filter(
    (tool) => typeof tool?.name === "string",
  );
  const runnableNames = new Set(
    (enabledTools.data ?? []).filter((tool) => tool.plugin_id === plugin.id).map((tool) => tool.tool_name),
  );
  const allGranted = (grants.data ?? []).every((grant) => grant.granted);

  return (
    <div className="grid w-full content-start gap-3 px-0.5 pb-4 pt-0.5">
      <SettingsGroup
        title={plugin.name}
        description={`${plugin.id} · v${plugin.version}`}
        actions={
          <label className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-muted-foreground">
            <span>{plugin.enabled ? t("pluginOn") : t("pluginOff")}</span>
            <Switch checked={plugin.enabled} onCheckedChange={(checked) => togglePlugin.mutate(checked)} />
          </label>
        }
      >
        {(grants.data ?? []).length > 0 ? (
          (grants.data ?? []).map((grant) => (
            <SettingsRow key={grant.permission} label={grant.permission} description={t("permissionRowDesc")}>
              <label className="inline-flex cursor-pointer select-none items-center gap-1.5 text-xs text-muted-foreground">
                <span>{grant.granted ? t("granted") : t("denied")}</span>
                <Switch
                  checked={grant.granted}
                  onCheckedChange={(granted) => setGrant.mutate({ permission: grant.permission, granted })}
                />
              </label>
            </SettingsRow>
          ))
        ) : (
          <SettingsRow label={t("noPermissions")} description={t("pureToolDesc")} />
        )}
      </SettingsGroup>

      <SettingsGroup title={t("tools")} description={t("toolsGroupDesc")}>
        <SettingsBlock>
          {manifestTools.map((tool) => (
            <ToolCard
              key={tool.name}
              pluginId={plugin.id}
              tool={tool}
              runnable={plugin.enabled && allGranted && runnableNames.has(tool.name)}
            />
          ))}
          {manifestTools.length === 0 && <p className="m-0 text-xs text-muted-foreground">{t("noTools")}</p>}
        </SettingsBlock>
      </SettingsGroup>

      <SettingsGroup
        title={t("invocations")}
        description={t("invocationsGroupDesc")}
        actions={
          (invocations.data ?? []).length > 0 ? (
            <Button variant="outline" size="sm" disabled={clearInvocations.isPending} onClick={() => clearInvocations.mutate()}>
              <Trash2 size={13} /> {t("invocationsClear")}
            </Button>
          ) : undefined
        }
      >
        <SettingsBlock>
          {(invocations.data ?? []).slice(0, 15).map((invocation) => (
            <InvocationRow
              key={invocation.id}
              invocation={invocation}
              onDelete={() => deleteInvocation.mutate(invocation.id)}
            />
          ))}
          {invocations.data?.length === 0 && <p className="m-0 text-xs text-muted-foreground">{t("noInvocations")}</p>}
        </SettingsBlock>
      </SettingsGroup>
    </div>
  );
}

interface PluginToolManifest {
  name: string;
  description?: string;
  input_schema?: {
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
}

/** 工具卡:展开后按 input_schema 生成输入表单,试运行并展示结果。 */
function ToolCard({
  pluginId,
  tool,
  runnable,
}: {
  pluginId: string;
  tool: PluginToolManifest;
  runnable: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<PluginInvocation | null>(null);

  const schema = tool.input_schema ?? {};
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
      return api<PluginInvocation>(`/api/plugins/${pluginId}/tools/${tool.name}/invoke`, {
        method: "POST",
        body: JSON.stringify({ input }),
      });
    },
    onSuccess: (invocation) => {
      setResult(invocation);
      void qc.invalidateQueries({ queryKey: ["plugin-invocations", pluginId] });
    },
  });

  const missingRequired = [...required].some((key) => !(values[key] ?? "").trim());

  return (
    <div className="overflow-hidden rounded-md border border-border bg-panel">
      <button type="button" className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent px-2 py-[9px] text-left hover:bg-secondary" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Terminal size={14} />
        <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-[11.5px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-[12.5px] [&_strong]:font-semibold">
          <strong>{tool.name}</strong>
          <small>{tool.description ?? ""}</small>
        </div>
        {!runnable && <small className="ml-auto whitespace-nowrap text-[10.5px] text-muted-foreground">{t("toolBlockedHint")}</small>}
      </button>
      {open && (
        <div className="grid gap-1.5 border-t border-border p-2">
          {fields.map(([key, spec]) => (
            <label className="grid gap-1 [&>span]:text-[11.5px] [&>span]:text-muted-foreground [&_em]:not-italic [&_em]:text-destructive" key={key}>
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
            <Button size="sm" disabled={!runnable || missingRequired || invoke.isPending} onClick={() => invoke.mutate()}>
              <Play size={13} /> {t("runTool")}
            </Button>
          </div>
          {result && (
            <pre className={cn("m-0 max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md px-2 py-1.5 font-mono text-[11px] leading-[1.5] [word-break:break-word]", result.status === "succeeded" ? "border border-[color-mix(in_oklab,#22c55e_30%,var(--border))] bg-[color-mix(in_oklab,#22c55e_8%,var(--background))]" : "border border-[color-mix(in_oklab,var(--destructive)_30%,var(--border))] bg-[color-mix(in_oklab,var(--destructive)_7%,var(--background))] text-destructive")}>
              {result.status === "succeeded"
                ? JSON.stringify(result.output, null, 2)
                : result.error ?? result.status}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function InvocationRow({ invocation, onDelete }: { invocation: PluginInvocation; onDelete: () => void }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const ok = invocation.status === "succeeded";
  return (
    <div className="overflow-hidden rounded-md border border-border bg-panel">
      <div className="flex items-stretch [&>button:first-child]:min-w-0 [&>button:first-child]:flex-1">
        <button type="button" className="flex w-full cursor-pointer items-center gap-1.5 border-0 bg-transparent px-2 py-[9px] text-left hover:bg-secondary" onClick={() => setOpen((value) => !value)}>
          {ok ? <CheckCircle2 size={14} className="text-[#16a34a]" /> : <CircleAlert size={14} className="text-destructive" />}
          <div className="min-w-0 [&_small]:block [&_small]:truncate [&_small]:text-[11.5px] [&_small]:text-muted-foreground [&_strong]:block [&_strong]:text-[12.5px] [&_strong]:font-semibold">
            <strong>{invocation.tool_name}</strong>
            <small>{invocation.status}</small>
          </div>
        </button>
        <button type="button" className="grid w-8 flex-none cursor-pointer place-items-center border-0 bg-transparent text-muted-foreground transition-colors duration-100 hover:bg-secondary hover:text-destructive" aria-label={t("delete")} onClick={onDelete}>
          <Trash2 size={13} />
        </button>
      </div>
      {open && (
        <pre className={cn("m-0 max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md px-2 py-1.5 font-mono text-[11px] leading-[1.5] [word-break:break-word]", ok ? "border border-[color-mix(in_oklab,#22c55e_30%,var(--border))] bg-[color-mix(in_oklab,#22c55e_8%,var(--background))]" : "border border-[color-mix(in_oklab,var(--destructive)_30%,var(--border))] bg-[color-mix(in_oklab,var(--destructive)_7%,var(--background))] text-destructive")}>
          {JSON.stringify(ok ? invocation.output : { input: invocation.input, error: invocation.error }, null, 2)}
        </pre>
      )}
    </div>
  );
}
