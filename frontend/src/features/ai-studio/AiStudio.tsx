import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, ImagePlus, Loader2, MessageSquarePlus, Pencil, Plus, Send, Sparkles, Trash2, Video } from "lucide-react";

import {
  api,
  assetFileUrl,
  assetThumbnailUrl,
  type GenerationCreateResponse,
  type GenerationJob,
  type GenerationModel,
  type Job,
  type Workspace,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { ConfigNotice } from "@/components/layout/ConfigNotice";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useImagePreview } from "@/components/ui/image-preview";
import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";
import { generationSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { usePersistentTab } from "@/lib/usePersistentTab";

type ProviderDefault = components["schemas"]["ProviderDefaultOut"];
type ProviderProfile = components["schemas"]["ProviderProfileOut"];
type GenerationSession = components["schemas"]["GenerationSessionOut"];

export function AiStudio({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [tab, setTab] = usePersistentTab<"chat" | "generate">("ai-studio", "chat", ["chat", "generate"]);

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
        <ChatWorkspace workspace={workspace} switcher={switcher} />
      ) : (
        <GenerateWorkspace workspace={workspace} switcher={switcher} />
      )}
    </div>
  );
}

/** Generation mirrors chat: left rail = sessions, center = current session transcript. */
function GenerateWorkspace({
  workspace,
  switcher,
}: {
  workspace: Workspace;
  switcher?: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const sessionKey = generationSessionSelectionKey(workspace.id);
  const [sessionId, setSessionId] = React.useState<string | null>(() => window.localStorage.getItem(sessionKey));
  const [prompt, setPrompt] = React.useState("");
  const [modelId, setModelId] = React.useState<string | null>(null);
  const [renamingSession, setRenamingSession] = React.useState<GenerationSession | null>(null);
  const [deletingSession, setDeletingSession] = React.useState<GenerationSession | null>(null);
  const threadRef = React.useRef<HTMLDivElement | null>(null);

  const sessions = useQuery({
    queryKey: ["generation-sessions", workspace.id],
    queryFn: () => api<GenerationSession[]>(`/api/generation/sessions?workspace_id=${workspace.id}`),
  });
  const models = useQuery({
    queryKey: ["generation-models"],
    queryFn: () => api<GenerationModel[]>("/api/generation/models"),
  });
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<ProviderProfile[]>("/api/settings/providers"),
  });
  const defaults = useQuery({
    queryKey: ["provider-defaults"],
    queryFn: () => api<ProviderDefault[]>("/api/settings/provider-defaults"),
  });
  const jobs = useQuery({
    queryKey: ["jobs", workspace.id, "ai_generation"],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspace.id}&kind=ai_generation`),
    refetchInterval: (query) =>
      query.state.data?.some((job) => job.status === "queued" || job.status === "running") ? 1000 : false,
    refetchOnWindowFocus: true,
  });
  const activeSession =
    (sessions.data ?? []).find((session) => session.id === sessionId) ?? (sessions.data ?? [])[0] ?? null;
  const sessionJobs = useQuery({
    queryKey: ["generation-jobs", workspace.id, activeSession?.id],
    enabled: Boolean(activeSession),
    queryFn: () =>
      api<GenerationJob[]>(`/api/generation/jobs?workspace_id=${workspace.id}&session_id=${activeSession!.id}`),
    refetchInterval: (query) => {
      const activeJobIds = new Set(
        (jobs.data ?? []).filter((job) => job.status === "queued" || job.status === "running").map((job) => job.id),
      );
      return query.state.data?.some((generation) => activeJobIds.has(generation.job_id)) ? 1000 : false;
    },
    refetchOnWindowFocus: true,
  });

  const selectedModel =
    (models.data ?? []).find((model) => model.id === modelId) ?? (models.data ?? [])[0] ?? null;
  const modelGroups = React.useMemo(() => {
    const grouped = new Map<string, GenerationModel[]>();
    for (const model of models.data ?? []) {
      grouped.set(model.kind, [...(grouped.get(model.kind) ?? []), model]);
    }
    return ["image", "video", ...[...grouped.keys()].filter((kind) => kind !== "image" && kind !== "video")]
      .filter((kind) => (grouped.get(kind) ?? []).length > 0)
      .map((kind) => ({ kind, models: grouped.get(kind) ?? [] }));
  }, [models.data]);
  const capabilityLabel = (kind: string) => (kind === "image" ? t("capImage") : kind === "video" ? t("capVideo") : kind);
  const capabilityMissing = (kind: string) => {
    const row = (defaults.data ?? []).find((item) => item.capability === kind);
    const profile = row?.provider_profile_id
      ? (providers.data ?? []).find((item) => item.id === row.provider_profile_id)
      : null;
    return defaults.isSuccess && providers.isSuccess && (!row?.provider_profile_id || !row.model || !profile?.enabled);
  };
  const selectedCapabilityMissing = selectedModel ? capabilityMissing(selectedModel.kind) : false;

  const createSession = useMutation({
    mutationFn: () =>
      api<GenerationSession>("/api/generation/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id }),
      }),
    onSuccess: (created) => {
      setSessionId(created.id);
      window.localStorage.setItem(sessionKey, created.id);
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    },
  });

  const createGeneration = useMutation({
    mutationFn: async () => {
      let targetSessionId = activeSession?.id;
      if (!targetSessionId) {
        const created = await api<GenerationSession>("/api/generation/sessions", {
          method: "POST",
          body: JSON.stringify({ workspace_id: workspace.id, title: prompt.trim().slice(0, 40) || undefined }),
        });
        targetSessionId = created.id;
        setSessionId(created.id);
        window.localStorage.setItem(sessionKey, created.id);
      }
      await api<GenerationCreateResponse>("/api/generation/jobs", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          session_id: targetSessionId,
          project_id: null,
          provider: selectedModel!.provider,
          model: selectedModel!.model,
          kind: selectedModel!.kind,
          prompt,
          parameters:
            selectedModel!.kind === "image"
              ? { size: "1024x576" }
              : { duration_seconds: 5, resolution: "720p", aspect_ratio: "16:9" },
        }),
      });
      return targetSessionId;
    },
    onSuccess: (targetSessionId) => {
      setPrompt("");
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, targetSessionId] });
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "ai_generation"] });
    },
  });
  const renameSession = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api<GenerationSession>(`/api/generation/sessions/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
    onSuccess: () => {
      setRenamingSession(null);
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    },
  });
  const deleteSession = useMutation({
    mutationFn: (id: string) => api(`/api/generation/sessions/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      setDeletingSession(null);
      if (sessionId === id) {
        setSessionId(null);
        window.localStorage.removeItem(sessionKey);
      }
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["jobs", workspace.id, "ai_generation"] });
    },
  });

  const succeededCount = (jobs.data ?? []).filter((job) => job.status === "succeeded").length;
  React.useEffect(() => {
    if (succeededCount > 0) {
      void qc.invalidateQueries({ queryKey: ["assets"] });
      void qc.invalidateQueries({ queryKey: ["generation-jobs", workspace.id, activeSession?.id] });
      void qc.invalidateQueries({ queryKey: ["generation-sessions", workspace.id] });
    }
  }, [succeededCount, qc, workspace.id, activeSession?.id]);

  const ordered = React.useMemo(() => [...(sessionJobs.data ?? [])].reverse(), [sessionJobs.data]);

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
  }, [activeSession?.id]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!prompt.trim() || !selectedModel || createGeneration.isPending) return;
    createGeneration.mutate();
  };

  return (
    <div className="chat-grid">
      <aside className="chat-sessions panel">
        <div className="panel-head">
          <h2>{t("generationSessionsTitle")}</h2>
          <Button variant="outline" size="sm" onClick={() => createSession.mutate()} disabled={createSession.isPending}>
            <Plus size={13} /> {t("generationNewSession")}
          </Button>
        </div>
        <div className="chat-session-list">
          {sessions.isSuccess && (sessions.data ?? []).length === 0 && (
            <div className="chat-session-empty">
              <MessageSquarePlus size={16} />
              <span>{t("generationNoSessions")}</span>
            </div>
          )}
          {(sessions.data ?? []).map((item) => (
            <ContextMenu key={item.id}>
              <ContextMenuTrigger asChild>
                <button
                  type="button"
                  className={activeSession?.id === item.id ? "chat-session active" : "chat-session"}
                  onClick={() => {
                    setSessionId(item.id);
                    window.localStorage.setItem(sessionKey, item.id);
                  }}
                >
                  <strong>{item.title}</strong>
                </button>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => setRenamingSession(item)}>
                  <Pencil /> {t("rename")}
                </ContextMenuItem>
                <ContextMenuSeparator />
                <ContextMenuItem destructive onSelect={() => setDeletingSession(item)}>
                  <Trash2 /> {t("delete")}
                </ContextMenuItem>
              </ContextMenuContent>
            </ContextMenu>
          ))}
        </div>
        <RenameDialog
          open={renamingSession !== null}
          title={t("renameGenerationSession")}
          initialValue={renamingSession?.title ?? ""}
          onCancel={() => setRenamingSession(null)}
          onSubmit={(title) => renamingSession && renameSession.mutate({ id: renamingSession.id, title })}
        />
        <ConfirmDialog
          open={deletingSession !== null}
          title={t("deleteConfirmTitle")}
          body={t("deleteGenerationSessionBody")}
          onCancel={() => setDeletingSession(null)}
          onConfirm={() => deletingSession && deleteSession.mutate(deletingSession.id)}
        />
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
          {selectedModel && selectedCapabilityMissing && (
            <ConfigNotice
              message={t("aiCapabilityNotConfigured").replace("{capability}", capabilityLabel(selectedModel.kind))}
              actionLabel={t("wfGoConfigure")}
              section={`providers:${selectedModel.kind}`}
            />
          )}
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
                <Select value={selectedModel.id} onValueChange={setModelId}>
                  <SelectTrigger className="composer-model-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {modelGroups.map((group) => (
                      <React.Fragment key={group.kind}>
                        <div className="generation-model-select-group">{capabilityLabel(group.kind)}</div>
                        {group.models.map((model) => (
                          <SelectItem key={model.id} value={model.id}>
                            {model.kind === "image" ? <ImagePlus size={12} /> : <Video size={12} />}
                            {model.model} · {model.provider}
                          </SelectItem>
                        ))}
                      </React.Fragment>
                    ))}
                  </SelectContent>
                </Select>
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
  const { openImagePreview } = useImagePreview();
  const status = job?.status ?? "queued";
  return (
    <>
      <div className="chat-bubble user">{String(generation.request.prompt ?? "")}</div>
      <div className="chat-bubble assistant">
        <div className="gen-turn">
          {generation.result_asset_id ? (
            <button
              type="button"
              className="gen-turn-image-button"
              onClick={() =>
                openImagePreview({
                  src: assetFileUrl(generation.result_asset_id!),
                  title: String(generation.request.prompt ?? generation.model),
                })
              }
            >
              <img className="gen-turn-image" src={assetThumbnailUrl(generation.result_asset_id)} alt="" loading="lazy" />
            </button>
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
