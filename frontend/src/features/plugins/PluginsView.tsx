import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plug, RadioTower, RefreshCcw, Terminal } from "lucide-react";

import { api, type Plugin, type PluginInvocation, type PluginTool } from "@/api/client";

export function PluginsView() {
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
  const scanPlugins = useMutation({
    mutationFn: () => api<Plugin[]>("/api/plugins/scan", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plugins"] });
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
  const invokeTool = useMutation({
    mutationFn: (tool: PluginTool) =>
      api<PluginInvocation>(`/api/plugins/${tool.plugin_id}/tools/${tool.tool_name}/invoke`, {
        method: "POST",
        body: JSON.stringify({ input: { source: "frontend_smoke" } }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plugin-invocations"] }),
  });

  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>插件</h1>
          <p>扫描本地 manifest，暴露 Skill 和 Tool 给应用与外部智能体。</p>
        </div>
        <button onClick={() => scanPlugins.mutate()}><RefreshCcw size={16} /> 扫描插件</button>
      </header>

      <section className="feature-grid three">
        <div className="panel feature-panel">
          <div className="panel-head"><h2>已安装</h2></div>
          <div className="plugin-list">
            {(plugins.data ?? []).map((plugin) => (
              <div className="plugin-row" key={plugin.id}>
                <Plug size={16} />
                <div>
                  <strong>{plugin.name}</strong>
                  <small>{plugin.id} · v{plugin.version}</small>
                </div>
                <button onClick={() => togglePlugin.mutate({ plugin, enabled: !plugin.enabled })}>
                  {plugin.enabled ? <CheckCircle2 size={14} /> : <RadioTower size={14} />}
                  {plugin.enabled ? "已启用" : "启用"}
                </button>
              </div>
            ))}
            {plugins.data?.length === 0 && <div className="empty-inline">把插件目录放到 ~/.mibu-new/plugins 后点击扫描</div>}
          </div>
        </div>

        <div className="panel feature-panel">
          <div className="panel-head"><h2>工具</h2></div>
          <div className="plugin-list">
            {(tools.data ?? []).map((tool) => (
              <div className="plugin-row" key={`${tool.plugin_id}:${tool.tool_name}`}>
                <Terminal size={16} />
                <div>
                  <strong>{tool.tool_name}</strong>
                  <small>{tool.plugin_name} · {tool.description}</small>
                </div>
                <button onClick={() => invokeTool.mutate(tool)}>调用</button>
              </div>
            ))}
            {tools.data?.length === 0 && <div className="empty-inline">启用插件后会显示可调用工具</div>}
          </div>
        </div>

        <div className="panel feature-panel">
          <div className="panel-head"><h2>调用记录</h2></div>
          <div className="plugin-list">
            {(invocations.data ?? []).slice(0, 12).map((invocation) => (
              <div className="plugin-row compact" key={invocation.id}>
                <RadioTower size={16} />
                <div>
                  <strong>{invocation.tool_name}</strong>
                  <small>{invocation.status} · {invocation.plugin_id}</small>
                </div>
              </div>
            ))}
            {invocations.data?.length === 0 && <div className="empty-inline">还没有工具调用记录</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
