import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CalendarClock, Film, FolderPlus, ImagePlus, Play, Plug, Plus, Scissors } from "lucide-react";

import { api, importAsset, type Asset, type Clip, type Project, type Sequence, type Track, type Workspace } from "@/api/client";
import "@/design/tokens.css";
import { AiStudio } from "@/features/ai-studio/AiStudio";
import { PluginsView } from "@/features/plugins/PluginsView";
import { SchedulerView } from "@/features/scheduler/SchedulerView";
import "./styles.css";

const queryClient = new QueryClient();
type StudioView = "editor" | "ai" | "scheduler" | "plugins";

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Workspace />
    </QueryClientProvider>
  );
}

function Workspace() {
  const qc = useQueryClient();
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: () => api<Workspace[]>("/api/workspaces") });
  const createWorkspace = useMutation({
    mutationFn: () => api<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify({ name: "默认工作区" }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workspaces"] }),
  });
  const workspace = workspaces.data?.[0] ?? null;

  if (workspaces.isLoading) return <div className="center">正在连接后端...</div>;
  if (!workspace) {
    return (
      <div className="center">
        <div className="welcome">
          <Film size={34} />
          <h1>Mibu New</h1>
          <p>先创建一个工作区，开始搭建新的 AI 视频创作工作台。</p>
          <button onClick={() => createWorkspace.mutate()}>
            <FolderPlus size={16} /> 创建默认工作区
          </button>
        </div>
      </div>
    );
  }
  return <Studio workspace={workspace} />;
}

function Studio({ workspace }: { workspace: Workspace }) {
  const [view, setView] = React.useState<StudioView>("editor");
  const qc = useQueryClient();
  const projects = useQuery({
    queryKey: ["projects", workspace.id],
    queryFn: () => api<Project[]>(`/api/projects?workspace_id=${workspace.id}`),
  });
  const project = projects.data?.[0] ?? null;
  const createProject = useMutation({
    mutationFn: () => api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ workspace_id: workspace.id, name: "第一个项目" }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", workspace.id] }),
  });

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><Film size={18} /> Mibu New</div>
        <button className={`nav ${view === "editor" ? "active" : ""}`} onClick={() => setView("editor")}><Scissors size={15} /> 剪辑</button>
        <button className={`nav ${view === "ai" ? "active" : ""}`} onClick={() => setView("ai")}><Bot size={15} /> AI Studio</button>
        <button className={`nav ${view === "scheduler" ? "active" : ""}`} onClick={() => setView("scheduler")}><CalendarClock size={15} /> 定时任务</button>
        <button className={`nav ${view === "plugins" ? "active" : ""}`} onClick={() => setView("plugins")}><Plug size={15} /> 插件</button>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <strong>{workspace.name}</strong>
            <span>{project ? project.name : "还没有项目"}</span>
          </div>
          {!project && <button onClick={() => createProject.mutate()}><Plus size={16} /> 新建项目</button>}
        </header>
        {view === "editor" && (project ? <Editor workspace={workspace} project={project} /> : <EmptyProject />)}
        {view === "ai" && <AiStudio workspace={workspace} project={project} />}
        {view === "scheduler" && <SchedulerView workspace={workspace} project={project} />}
        {view === "plugins" && <PluginsView />}
      </main>
    </div>
  );
}

function EmptyProject() {
  return (
    <div className="empty">
      <Scissors size={42} />
      <h2>创建项目后开始剪辑</h2>
    </div>
  );
}

function Editor({ workspace, project }: { workspace: Workspace; project: Project }) {
  const qc = useQueryClient();
  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}&project_id=${project.id}`),
  });
  const sequences = useQuery({
    queryKey: ["sequences", project.id],
    queryFn: () => api<Sequence[]>(`/api/projects/${project.id}/sequences`),
  });
  const sequence = sequences.data?.[0] ?? null;
  const createAsset = useMutation({
    mutationFn: () =>
      api<Asset>("/api/assets", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          project_id: project.id,
          kind: "video",
          name: `示例素材 ${(assets.data?.length ?? 0) + 1}`,
          original_filename: "sample.mp4",
          file_key: "samples/sample.mp4",
          media_info: { duration: 8, width: 1920, height: 1080 },
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] }),
  });
  const uploadAsset = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, projectId: project.id, file }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] }),
  });
  const createSequence = useMutation({
    mutationFn: () =>
      api<Sequence>("/api/sequences", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, project_id: project.id, name: "主时间线" }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequences", project.id] }),
  });
  const insertClip = useMutation({
    mutationFn: ({ asset, track }: { asset: Asset; track: Track }) =>
      api<Sequence>(`/api/sequences/${sequence?.id}/clips`, {
        method: "POST",
        body: JSON.stringify({
          track_id: track.id,
          asset_id: asset.id,
          timeline_start: (track.clips ?? []).length * 8,
          src_in: 0,
          src_out: Number(asset.media_info.duration ?? 8),
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequences", project.id] }),
  });

  const videoTrack = sequence?.tracks?.find((track) => track.kind === "video");

  return (
    <div className="editor-grid">
      <section className="panel media-panel">
        <div className="panel-head">
          <h2>素材</h2>
          <div className="media-actions">
            <label className="upload-button">
              <input
                type="file"
                accept="video/*,audio/*,image/*"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) uploadAsset.mutate(file);
                  event.currentTarget.value = "";
                }}
              />
              <ImagePlus size={15} /> 导入
            </label>
            <button onClick={() => createAsset.mutate()}><ImagePlus size={15} /> 示例</button>
          </div>
        </div>
        <div className="asset-list">
          {(assets.data ?? []).map((asset) => (
            <button
              className="asset-card"
              key={asset.id}
              onClick={() => videoTrack && insertClip.mutate({ asset, track: videoTrack })}
              disabled={!videoTrack}
            >
              <span>{asset.kind}</span>
              <strong>{asset.name}</strong>
              <small>{String(asset.media_info.duration ?? "?")}s</small>
            </button>
          ))}
        </div>
      </section>
      <section className="panel monitor">
        <div className="monitor-frame"><Play size={42} /></div>
      </section>
      <section className="panel inspector">
        <div className="panel-head"><h2>检查器</h2></div>
        {sequence ? (
          <dl>
            <dt>时间线</dt><dd>{sequence.name}</dd>
            <dt>Revision</dt><dd>{sequence.revision}</dd>
            <dt>规格</dt><dd>{sequence.width}x{sequence.height} / {sequence.fps}fps</dd>
          </dl>
        ) : (
          <button onClick={() => createSequence.mutate()}><Plus size={16} /> 创建主时间线</button>
        )}
      </section>
      <section className="timeline panel">
        {sequence ? <Timeline sequence={sequence} /> : <div className="empty small">创建时间线后可拖入素材</div>}
      </section>
    </div>
  );
}

function Timeline({ sequence }: { sequence: Sequence }) {
  return (
    <div className="timeline-inner">
      {(sequence.tracks ?? []).map((track) => (
        <div className="track" key={track.id}>
          <div className="track-label">{track.name}</div>
          <div className="track-lane">
            {(track.clips ?? []).map((clip) => (
              <div
                className="clip"
                key={clip.id}
                style={{
                  left: `${clip.timeline_start * 20}px`,
                  width: `${Math.max(28, (clip.src_out - clip.src_in) * 20)}px`,
                }}
              >
                {clip.asset_id.slice(0, 6)}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
