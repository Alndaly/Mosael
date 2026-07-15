import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ImagePlus, Sparkles, Video } from "lucide-react";

import {
  api,
  type GenerationCreateResponse,
  type GenerationJob,
  type GenerationModel,
  type Job,
  type Project,
  type Workspace,
} from "@/api/client";

export function AiStudio({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ["generation-models"],
    queryFn: () => api<GenerationModel[]>("/api/generation/models"),
  });
  const generations = useQuery({
    queryKey: ["generation-jobs", workspace.id],
    queryFn: () => api<GenerationJob[]>(`/api/generation/jobs?workspace_id=${workspace.id}`),
  });
  const jobs = useQuery({
    queryKey: ["jobs", workspace.id, "ai_generation"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspace.id}&kind=ai_generation`),
  });
  const createGeneration = useMutation({
    mutationFn: (kind: "image" | "video") =>
      api<GenerationCreateResponse>("/api/generation/jobs", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          project_id: project?.id ?? null,
          provider: kind === "image" ? "alibaba" : "bytedance",
          model: kind === "image" ? "qwen-image" : "seedance",
          kind,
          prompt: kind === "image" ? "A refined key visual for an AI video editing project" : "A concise cinematic product shot with smooth motion",
          parameters: kind === "image" ? { size: "1024x1024" } : { duration_seconds: 5, aspect_ratio: "16:9" },
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id] });
      qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "ai_generation"] });
    },
  });

  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>AI Studio</h1>
          <p>统一管理图片、视频生成模型和生成任务。</p>
        </div>
        <div className="feature-actions">
          <button onClick={() => createGeneration.mutate("image")}><ImagePlus size={16} /> 生成图片</button>
          <button onClick={() => createGeneration.mutate("video")}><Video size={16} /> 生成视频</button>
        </div>
      </header>

      <section className="feature-grid two">
        <div className="panel feature-panel">
          <div className="panel-head"><h2>模型</h2></div>
          <div className="model-list">
            {(models.data ?? []).map((model) => (
              <div className="model-row" key={model.id}>
                <span>{model.kind === "image" ? <ImagePlus size={16} /> : <Video size={16} />}</span>
                <div>
                  <strong>{model.model}</strong>
                  <small>{model.provider}</small>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel feature-panel">
          <div className="panel-head"><h2>生成队列</h2></div>
          <div className="job-list">
            {(generations.data ?? []).map((generation) => {
              const job = jobs.data?.find((item) => item.id === generation.job_id);
              return (
                <div className="job-row" key={generation.id}>
                  <Bot size={16} />
                  <div>
                    <strong>{generation.model}</strong>
                    <small>{job?.status ?? "queued"} · {String(generation.request.prompt ?? "")}</small>
                  </div>
                  <Sparkles size={15} />
                </div>
              );
            })}
            {generations.data?.length === 0 && <div className="empty-inline">还没有生成任务</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
