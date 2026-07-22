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
      <div className="feature-view">
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
    <div className="feature-view">
      <div className="plugins-shell">
        <aside className="plugins-list panel">
          <div className="panel-head">
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
          <div className="plugins-list-body">
            {(plugins.data ?? []).map((plugin) => (
              <button
                key={plugin.id}
                type="button"
                className={selected?.id === plugin.id ? "plugins-item active" : "plugins-item"}
                onClick={() => setSelectedId(plugin.id)}
              >
                <span className={plugin.enabled ? "plugins-dot on" : "plugins-dot"} />
                <span className="plugins-item-text">
                  <strong>{plugin.name}</strong>
                  <small>v{plugin.version}</small>
                </span>
              </button>
            ))}
          </div>
        </aside>
        <div className="plugins-detail">
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
    <div className="plugins-detail-body">
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
    <div className="plugin-tool-card">
      <button type="button" className="plugin-tool-head" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Terminal size={14} />
        <div className="plugin-tool-title">
          <strong>{tool.name}</strong>
          <small>{tool.description ?? ""}</small>
        </div>
        {!runnable && <small className="plugin-tool-blocked">{t("toolBlockedHint")}</small>}
      </button>
      {open && (
        <div className="plugin-tool-body">
          {fields.map(([key, spec]) => (
            <label className="plugin-field" key={key}>
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
          <div className="plugin-tool-actions">
            <Button size="sm" disabled={!runnable || missingRequired || invoke.isPending} onClick={() => invoke.mutate()}>
              <Play size={13} /> {t("runTool")}
            </Button>
          </div>
          {result && (
            <pre className={result.status === "succeeded" ? "plugin-result ok" : "plugin-result bad"}>
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
    <div className="plugin-tool-card">
      <div className="inv-row-head">
        <button type="button" className="plugin-tool-head" onClick={() => setOpen((value) => !value)}>
          {ok ? <CheckCircle2 size={14} className="text-[#16a34a]" /> : <CircleAlert size={14} className="text-destructive" />}
          <div className="plugin-tool-title">
            <strong>{invocation.tool_name}</strong>
            <small>{invocation.status}</small>
          </div>
        </button>
        <button type="button" className="inv-row-delete" aria-label={t("delete")} onClick={onDelete}>
          <Trash2 size={13} />
        </button>
      </div>
      {open && (
        <pre className={ok ? "plugin-result ok" : "plugin-result bad"}>
          {JSON.stringify(ok ? invocation.output : { input: invocation.input, error: invocation.error }, null, 2)}
        </pre>
      )}
    </div>
  );
}
