import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, ImagePlus, Loader2, Send, Sparkles, Video } from "lucide-react";

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
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";

export function AiStudio({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  const [tab, setTab] = React.useState<"chat" | "generate">("chat");

  const switcher = (
    <div className="seg" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={tab === "chat"}
        className={tab === "chat" ? "seg-btn active" : "seg-btn"}
        onClick={() => setTab("chat")}
      >
        {t("aiTabChat")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={tab === "generate"}
        className={tab === "generate" ? "seg-btn active" : "seg-btn"}
        onClick={() => setTab("generate")}
      >
        {t("aiTabGenerate")}
      </button>
    </div>
  );

  return (
    <div className="feature-view ai-studio-view">
      {tab === "chat" ? (
        <ChatWorkspace workspace={workspace} project={project} switcher={switcher} />
      ) : (
        <GenerateWorkspace workspace={workspace} project={project} switcher={switcher} />
      )}
    </div>
  );
}

/**
 * Generation, shaped exactly like the chat surface: models live in the left
 * rail (where chat keeps its sessions), each generation renders as a
 * prompt-bubble + result-row pair in the centered thread, and the same
 * composer sits at the bottom.
 */
function GenerateWorkspace({
  workspace,
  project,
  switcher,
}: {
  workspace: Workspace;
  project: Project | null;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [prompt, setPrompt] = React.useState("");
  const [modelId, setModelId] = React.useState<string | null>(null);
  const threadRef = React.useRef<HTMLDivElement | null>(null);

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

  // Oldest first, like a conversation.
  const ordered = React.useMemo(() => [...(generations.data ?? [])].reverse(), [generations.data]);

  // 贴底跟随(与聊天一致):结果图片/视频异步加载会持续长高,
  // 只要用户没往上翻就保持钉在底部。
  React.useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    let stick = true;
    const onScroll = () => {
      stick = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    const observer = new MutationObserver(() => {
      if (stick) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el, { childList: true, subtree: true, characterData: true });
    el.scrollTop = el.scrollHeight;
    return () => {
      el.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, []);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!prompt.trim() || !selectedModel || createGeneration.isPending) return;
    createGeneration.mutate();
  };

  return (
    <div className="chat-grid">
      <aside className="chat-sessions panel">
        <div className="panel-head">
          <h2>{t("generationModels")}</h2>
        </div>
        <div className="chat-session-list">
          {(models.data ?? []).map((model) => (
            <button
              key={model.id}
              type="button"
              className={selectedModel?.id === model.id ? "chat-session active" : "chat-session"}
              onClick={() => setModelId(model.id)}
            >
              <strong>
                {model.kind === "image" ? <ImagePlus size={12} /> : <Video size={12} />} {model.model}
              </strong>
              <small>{model.provider}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="chat-main panel">
        <div className="chat-thread" ref={threadRef}>
          {ordered.length === 0 && (
            <EmptyState icon={<Sparkles size={22} />} title={t("noGenerationJobs")} body={t("promptPlaceholder")} />
          )}
          {ordered.map((generation) => (
            <GenerationTurn
              key={generation.id}
              generation={generation}
              job={jobs.data?.find((item) => item.id === generation.job_id) ?? null}
            />
          ))}
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <textarea
            rows={2}
            value={prompt}
            placeholder={t("promptPlaceholder")}
            onChange={(event) => {
              setPrompt(event.target.value);
              event.target.style.height = "auto";
              event.target.style.height = `${Math.min(event.target.scrollHeight, 220)}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit(event);
              }
            }}
          />
          <div className="chat-composer-bar">
            <div className="chat-composer-left">
              {switcher}
              {selectedModel && (
                <span className="composer-model">
                  {selectedModel.kind === "image" ? <ImagePlus size={11} /> : <Video size={11} />}
                  {selectedModel.model}
                </span>
              )}
            </div>
            <Button
              type="submit"
              size="icon"
              className="chat-send"
              aria-label={t("generate")}
              disabled={!prompt.trim() || !selectedModel || createGeneration.isPending}
            >
              {createGeneration.isPending ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}

function GenerationTurn({ generation, job }: { generation: GenerationJob; job: Job | null }) {
  const t = useI18n();
  const status = job?.status ?? "queued";
  return (
    <>
      <div className="chat-bubble user">{String(generation.request.prompt ?? "")}</div>
      <div className="chat-bubble assistant">
        <div className="gen-turn">
          {generation.result_asset_id ? (
            <img className="gen-turn-image" src={assetThumbnailUrl(generation.result_asset_id)} alt="" loading="lazy" />
          ) : status === "failed" ? (
            <span className="gen-turn-status failed">
              <CircleAlert size={13} /> {t("genFailed")}
              {job?.error ? ` · ${job.error}` : ""}
            </span>
          ) : (
            <span className="gen-turn-status">
              <Loader2 size={13} className="spin" /> {status === "running" ? t("generating") : t("genQueued")}
            </span>
          )}
          <small>
            {generation.provider} · {generation.model}
          </small>
        </div>
      </div>
    </>
  );
}
