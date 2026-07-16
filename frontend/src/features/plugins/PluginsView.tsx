import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Play, Plug, RadioTower, RefreshCcw, ShieldCheck, Terminal } from "lucide-react";

import { api, type Plugin, type PluginInvocation, type PluginPermissionGrant, type PluginTool } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function PluginsView() {
  const t = useI18n();
  const qc = useQueryClient();
  const plugins = useQuery({
    queryKey: ["plugins"],
    queryFn: () => api<Plugin[]>("/api/plugins"),
  });
  const tools = useQuery({
    queryKey: ["plugin-tools"],
    queryFn: () => api<PluginTool[]>("/api/plugins/tools"),
  });
  const invocations = useQuery({
    queryKey: ["plugin-invocations"],
    queryFn: () => api<PluginInvocation[]>("/api/plugins/invocations"),
  });
  const permissions = useQuery({
    queryKey: ["plugin-permissions", (plugins.data ?? []).map((plugin) => plugin.id).join(",")],
    enabled: Boolean(plugins.data),
    queryFn: async () => {
      const entries = await Promise.all(
        (plugins.data ?? []).map(async (plugin) => [
          plugin.id,
          await api<PluginPermissionGrant[]>(`/api/plugins/${plugin.id}/permissions`),
        ] as const),
      );
      return Object.fromEntries(entries) as Record<string, PluginPermissionGrant[]>;
    },
  });
  const scanPlugins = useMutation({
    mutationFn: () => api<Plugin[]>("/api/plugins/scan", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plugins"] });
      qc.invalidateQueries({ queryKey: ["plugin-permissions"] });
      qc.invalidateQueries({ queryKey: ["plugin-tools"] });
    },
  });
  const togglePlugin = useMutation({
    mutationFn: ({ plugin, enabled }: { plugin: Plugin; enabled: boolean }) =>
      api<Plugin>(`/api/plugins/${plugin.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plugins"] });
      qc.invalidateQueries({ queryKey: ["plugin-tools"] });
    },
  });
  const grantPlugin = useMutation({
    mutationFn: (plugin: Plugin) => {
      const grants = Object.fromEntries(
        ((plugin.manifest.permissions as string[] | undefined) ?? []).map((permission) => [permission, true]),
      );
      return api<PluginPermissionGrant[]>(`/api/plugins/${plugin.id}/permissions`, {
        method: "PATCH",
        body: JSON.stringify({ grants }),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plugin-permissions"] });
      qc.invalidateQueries({ queryKey: ["plugin-tools"] });
    },
  });

  return (
    <div className="feature-view">
      <div className="feature-toolbar">
        <Button onClick={() => scanPlugins.mutate()}><RefreshCcw size={16} /> {t("scanPlugins")}</Button>
      </div>

      <section className="feature-grid three">
        <div className="panel feature-panel">
          <div className="panel-head"><h2>{t("installed")}</h2></div>
          <div className="plugin-list">
            {(plugins.data ?? []).map((plugin) => (
              <div className="plugin-row" key={plugin.id}>
                <Plug size={16} />
                <div>
                  <strong>{plugin.name}</strong>
                  <small>
                    {plugin.id} · v{plugin.version} · {permissionLabel(permissions.data?.[plugin.id] ?? [], t)}
                  </small>
                </div>
                <div className="plugin-actions">
                  {(permissions.data?.[plugin.id] ?? []).some((grant) => !grant.granted) && (
                    <Button size="sm" variant="outline" onClick={() => grantPlugin.mutate(plugin)}>
                      <ShieldCheck size={14} /> {t("grant")}
                    </Button>
                  )}
                  <Button size="sm" variant={plugin.enabled ? "secondary" : "outline"} onClick={() => togglePlugin.mutate({ plugin, enabled: !plugin.enabled })}>
                    {plugin.enabled ? <CheckCircle2 size={14} /> : <RadioTower size={14} />}
                    {plugin.enabled ? t("enabled") : t("enable")}
                  </Button>
                </div>
              </div>
            ))}
            {plugins.data?.length === 0 && <div className="empty-inline">{t("noPlugins")}</div>}
          </div>
        </div>

        <div className="panel feature-panel">
          <div className="panel-head"><h2>{t("tools")}</h2></div>
          <div className="plugin-list">
            {(tools.data ?? []).map((tool) => (
              <ToolCard key={`${tool.plugin_id}:${tool.tool_name}`} tool={tool} />
            ))}
            {tools.data?.length === 0 && <div className="empty-inline">{t("noTools")}</div>}
          </div>
        </div>

        <div className="panel feature-panel">
          <div className="panel-head"><h2>{t("invocations")}</h2></div>
          <div className="plugin-list">
            {(invocations.data ?? []).slice(0, 20).map((invocation) => (
              <InvocationRow key={invocation.id} invocation={invocation} />
            ))}
            {invocations.data?.length === 0 && <div className="empty-inline">{t("noInvocations")}</div>}
          </div>
        </div>
      </section>
    </div>
  );
}

/** 工具卡:展开后按 input_schema 生成输入表单,试运行并展示结果。 */
function ToolCard({ tool }: { tool: PluginTool }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<PluginInvocation | null>(null);

  const schema = (tool.input_schema ?? {}) as {
    properties?: Record<string, { type?: string; description?: string }>;
    required?: string[];
  };
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
      return api<PluginInvocation>(`/api/plugins/${tool.plugin_id}/tools/${tool.tool_name}/invoke`, {
        method: "POST",
        body: JSON.stringify({ input }),
      });
    },
    onSuccess: (invocation) => {
      setResult(invocation);
      void qc.invalidateQueries({ queryKey: ["plugin-invocations"] });
    },
  });

  const missingRequired = [...required].some((key) => !(values[key] ?? "").trim());

  return (
    <div className="plugin-tool-card">
      <button type="button" className="plugin-tool-head" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Terminal size={14} />
        <div className="plugin-tool-title">
          <strong>{tool.tool_name}</strong>
          <small>{tool.plugin_name} · {tool.description}</small>
        </div>
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
            <Button size="sm" disabled={missingRequired || invoke.isPending} onClick={() => invoke.mutate()}>
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

function InvocationRow({ invocation }: { invocation: PluginInvocation }) {
  const [open, setOpen] = React.useState(false);
  const ok = invocation.status === "succeeded";
  return (
    <div className="plugin-tool-card">
      <button type="button" className="plugin-tool-head" onClick={() => setOpen((value) => !value)}>
        {ok ? <CheckCircle2 size={14} className="inv-ok" /> : <CircleAlert size={14} className="inv-bad" />}
        <div className="plugin-tool-title">
          <strong>{invocation.tool_name}</strong>
          <small>
            {invocation.status} · {invocation.plugin_id}
          </small>
        </div>
      </button>
      {open && (
        <pre className={ok ? "plugin-result ok" : "plugin-result bad"}>
          {JSON.stringify(ok ? invocation.output : { input: invocation.input, error: invocation.error }, null, 2)}
        </pre>
      )}
    </div>
  );
}

function permissionLabel(grants: PluginPermissionGrant[], t: ReturnType<typeof useI18n>) {
  if (grants.length === 0) return t("noPermissions");
  const granted = grants.filter((grant) => grant.granted).length;
  return `${granted}/${grants.length} ${t("permissions")}`;
}
