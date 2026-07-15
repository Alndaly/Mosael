import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, ImagePlus, Loader2, Sparkles, Video } from "lucide-react";

import {
  api,
  assetThumbnailUrl,
  type GenerationCreateResponse,
  type GenerationJob,
  type GenerationModel,
  type Job,
  type Project,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";

export function AiStudio({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const [tab, setTab] = React.useState<"chat" | "generate">("chat");

  return (
    <div className="feature-view ai-studio-view">
      <header className="feature-head">
        <div>
          <h1>AI Studio</h1>
          <p>{t("aiDescription")}</p>
        </div>
        <div className="panel-tabs">
          <button
            type="button"
            className={tab === "chat" ? "panel-tab active" : "panel-tab"}
            onClick={() => setTab("chat")}
          >
            {t("aiTabChat")}
          </button>
          <button
            type="button"
            className={tab === "generate" ? "panel-tab active" : "panel-tab"}
            onClick={() => setTab("generate")}
          >
            {t("aiTabGenerate")}
          </button>
        </div>
      </header>
      {tab === "chat" ? <ChatWorkspace workspace={workspace} project={project} /> : <GeneratePanel workspace={workspace} project={project} />}
    </div>
  );
}

function GeneratePanel({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [prompt, setPrompt] = React.useState("");
  const [modelId, setModelId] = React.useState<string | null>(null);

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
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 1000 : false,
    refetchIntervalInBackground: true,
  });

  const selectedModel =
    (models.data ?? []).find((model) => model.id === modelId) ?? (models.data ?? [])[0] ?? null;

  const createGeneration = useMutation({
    mutationFn: () =>
      api<GenerationCreateResponse>("/api/generation/jobs", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          project_id: project?.id ?? null,
          provider: selectedModel!.provider,
          model: selectedModel!.model,
          kind: selectedModel!.kind,
          prompt,
          parameters:
            selectedModel!.kind === "image"
              ? { size: "1024x576" }
              : { duration_seconds: 5, resolution: "720p", aspect_ratio: "16:9" },
        }),
      }),
    onSuccess: () => {
      setPrompt("");
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "ai_generation"] });
    },
  });

  // Refresh assets when a generation lands.
  const succeededCount = (jobs.data ?? []).filter((job) => job.status === "succeeded").length;
  React.useEffect(() => {
    if (succeededCount > 0) {
      void qc.invalidateQueries({ queryKey: ["assets"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id] });
    }
  }, [succeededCount, qc, workspace.id]);

  return (
    <div>
      <section className="gen-compose panel">
        <textarea
          className="gen-prompt"
          rows={3}
          placeholder={t("promptPlaceholder")}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <div className="gen-compose-row">
          <div className="gen-models">
            {(models.data ?? []).map((model) => (
              <button
                key={model.id}
                type="button"
                className={selectedModel?.id === model.id ? "gen-model active" : "gen-model"}
                onClick={() => setModelId(model.id)}
              >
                {model.kind === "image" ? <ImagePlus size={13} /> : <Video size={13} />}
                {model.model}
              </button>
            ))}
          </div>
          <Button
            onClick={() => createGeneration.mutate()}
            disabled={!prompt.trim() || !selectedModel || createGeneration.isPending}
          >
            <Sparkles size={15} /> {t("generate")}
          </Button>
        </div>
      </section>

      <h2 className="section-label" style={{ marginTop: 18 }}>
        <Sparkles size={13} /> {t("generationQueue")}
      </h2>
      <div className="gen-queue">
        {(generations.data ?? []).map((generation) => {
          const job = jobs.data?.find((item) => item.id === generation.job_id);
          return <GenerationRow key={generation.id} generation={generation} job={job ?? null} />;
        })}
        {generations.data?.length === 0 && <div className="empty-inline">{t("noGenerationJobs")}</div>}
      </div>
    </div>
  );
}

function GenerationRow({ generation, job }: { generation: GenerationJob; job: Job | null }) {
  const t = useI18n();
  const status = job?.status ?? "queued";
  return (
    <div className="gen-row">
      <div className="gen-thumb">
        {generation.result_asset_id ? (
          <img src={assetThumbnailUrl(generation.result_asset_id)} alt="" loading="lazy" />
        ) : status === "failed" ? (
          <CircleAlert size={16} />
        ) : (
          <Loader2 size={16} className="spin" />
        )}
      </div>
      <div className="gen-row-body">
        <strong>{String(generation.request.prompt ?? "")}</strong>
        <small>
          {generation.provider} · {generation.model}
          {job?.error ? ` · ${job.error}` : ""}
        </small>
      </div>
      <Badge variant={status === "failed" ? "outline" : "secondary"}>
        {status === "succeeded" ? (
          <>
            <CircleCheck size={11} /> {t("genDone")}
          </>
        ) : status === "failed" ? (
          t("genFailed")
        ) : status === "running" ? (
          t("generating")
        ) : (
          t("genQueued")
        )}
      </Badge>
    </div>
  );
}
