import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  ImagePlus,
  Loader2,
  MessageSquarePlus,
  Pencil,
  Plus,
  Send,
  Sparkles,
  Trash2,
  Upload,
  Video,
  X,
} from "lucide-react";

import {
  api,
  assetFileUrl,
  assetThumbnailUrl,
  importAsset,
  type Asset,
  type GenerationCreateResponse,
  type GenerationJob,
  type GenerationModel,
  type Job,
  type Workspace,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

const FALLBACK_IMAGE_SIZES = ["1024x1024"];
const FALLBACK_VIDEO_RESOLUTIONS = ["720p"];
const FALLBACK_ASPECT_RATIOS = ["16:9"];
const ENGINE_SEP = "::";

type GenerationConfig = {
  size: string;
  numImages: string;
  seed: string;
  negativePrompt: string;
  durationSeconds: string;
  resolution: string;
  aspectRatio: string;
  firstFrameUrl: string;
  firstFrameAssetId: string;
  firstFrameAssetName: string;
  referenceImageAssetId: string;
  referenceImageAssetName: string;
  usePreviousImage: boolean;
};

type GenerationEngineOption = GenerationModel & {
  value: string;
  provider_profile_id: string;
  label: string;
};

function capabilityList(model: GenerationModel | null, key: string, fallback: string[]): string[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => String(item).trim()).filter(Boolean);
  return items.length > 0 ? items : fallback;
}

function capabilityNumberList(model: GenerationModel | null, key: string, fallback: number[]): number[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
  return items.length > 0 ? items : fallback;
}

function capabilityString(model: GenerationModel | null, key: string, fallback: string): string {
  const value = model?.capabilities?.[key];
  return typeof value === "string" ? value : fallback;
}

function capabilityNumber(model: GenerationModel | null, key: string, fallback: number): number {
  const value = Number(model?.capabilities?.[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

function parameterKeys(model: GenerationModel | null): string[] {
  return capabilityList(model, "parameter_keys", []);
}

function supportsParameter(model: GenerationModel | null, key: string) {
  const keys = parameterKeys(model);
  return keys.length === 0 || keys.includes(key);
}

function imageSizeOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "size")) return [];
  return capabilityList(model, "sizes", FALLBACK_IMAGE_SIZES);
}

function videoResolutionOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "resolution")) return [];
  return capabilityList(model, "resolutions", FALLBACK_VIDEO_RESOLUTIONS);
}

function aspectRatioOptions(model: GenerationModel | null): string[] {
  if (!supportsParameter(model, "aspect_ratio")) return [];
  return capabilityList(model, "aspect_ratios", FALLBACK_ASPECT_RATIOS);
}

function durationOptions(model: GenerationModel | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  return capabilityNumberList(model, "duration_seconds", [5]);
}

function maxImages(model: GenerationModel | null): number {
  return capabilityNumber(model, "max_num_images", 4);
}

function defaultGenerationConfig(model: GenerationModel | null): GenerationConfig {
  const sizes = imageSizeOptions(model);
  const durations = durationOptions(model);
  const resolutions = videoResolutionOptions(model);
  const ratios = aspectRatioOptions(model);
  return {
    size: capabilityString(model, "default_size", sizes[0] ?? ""),
    numImages: "1",
    seed: "",
    negativePrompt: "",
    durationSeconds: String(capabilityNumber(model, "default_duration_seconds", durations[0] ?? 5)),
    resolution: capabilityString(model, "default_resolution", resolutions[0] ?? ""),
    aspectRatio: capabilityString(model, "default_aspect_ratio", ratios[0] ?? ""),
    firstFrameUrl: "",
    firstFrameAssetId: "",
    firstFrameAssetName: "",
    referenceImageAssetId: "",
    referenceImageAssetName: "",
    usePreviousImage: true,
  };
}

function generationParameters(model: GenerationModel, config: GenerationConfig) {
  if (model.kind === "image") {
    const params: Record<string, string | number> = {};
    if (supportsParameter(model, "size") && config.size) params.size = config.size;
    if (supportsParameter(model, "num_images")) params.num_images = Math.max(1, Math.min(maxImages(model), Number(config.numImages) || 1));
    if (supportsParameter(model, "seed") && config.seed.trim()) params.seed = Number(config.seed);
    return params;
  }
  const params: Record<string, string | number> = {};
  if (supportsParameter(model, "duration_seconds")) {
    params.duration_seconds = Math.max(1, Math.min(capabilityNumber(model, "max_duration_seconds", 10), Number(config.durationSeconds) || 5));
  }
  if (supportsParameter(model, "resolution") && config.resolution) params.resolution = config.resolution;
  if (supportsParameter(model, "aspect_ratio") && config.aspectRatio) params.aspect_ratio = config.aspectRatio;
  if (supportsParameter(model, "first_frame") && config.firstFrameUrl.trim()) params.first_frame_url = config.firstFrameUrl.trim();
  return params;
}

function generationOptionValue(providerProfileId: string, kind: string, model: string) {
  return [providerProfileId, kind, model].join(ENGINE_SEP);
}

function buildGenerationEngineOptions(
  catalog: GenerationModel[],
  profiles: ProviderProfile[],
  defaults: ProviderDefault[],
): GenerationEngineOption[] {
  const enabledProfiles = profiles.filter((profile) => profile.enabled);
  const byProviderKind = new Map<string, GenerationModel[]>();
  for (const model of catalog) {
    const key = `${model.provider}:${model.kind}`;
    byProviderKind.set(key, [...(byProviderKind.get(key) ?? []), model]);
  }
  const options = new Map<string, GenerationEngineOption>();
  const add = (profile: ProviderProfile, kind: string, modelName: string, source?: GenerationModel) => {
    if (!modelName) return;
    const providerKind = byProviderKind.get(`${profile.vendor}:${kind}`) ?? [];
    const model = source ?? providerKind.find((item) => item.model === modelName) ?? providerKind[0];
    const value = generationOptionValue(profile.id, kind, modelName);
    options.set(value, {
      id: model?.id ?? value,
      provider: profile.vendor,
      kind,
      model: modelName,
      enabled: true,
      capabilities: model?.capabilities ?? {},
      adapter_available: model?.adapter_available ?? false,
      provider_profile_id: profile.id,
      value,
      label: `${profile.name} · ${modelName}`,
    });
  };

  for (const profile of enabledProfiles) {
    for (const model of catalog.filter((item) => item.provider === profile.vendor)) {
      add(profile, model.kind, model.model, model);
    }
    for (const row of defaults) {
      if ((row.capability === "image" || row.capability === "video") && row.provider_profile_id === profile.id) {
        add(profile, row.capability, row.model);
      }
    }
  }
  return [...options.values()];
}

function findGenerationOption(
  options: GenerationEngineOption[],
  providerProfileId: string,
  kind: string,
  model: string,
) {
  return options.find((option) => option.value === generationOptionValue(providerProfileId, kind, model)) ?? null;
}

function defaultGenerationOption(options: GenerationEngineOption[], defaults: ProviderDefault[], kind: "image" | "video") {
  const row = defaults.find((item) => item.capability === kind);
  if (!row?.provider_profile_id || !row.model) return null;
  return findGenerationOption(options, row.provider_profile_id, kind, row.model);
}

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
  const { openImagePreview } = useImagePreview();
  const sessionKey = generationSessionSelectionKey(workspace.id);
  const [sessionId, setSessionId] = React.useState<string | null>(() => window.localStorage.getItem(sessionKey));
  const [prompt, setPrompt] = React.useState("");
  const [modelId, setModelId] = React.useState<string | null>(null);
  const [generationConfig, setGenerationConfig] = React.useState<GenerationConfig>(() => defaultGenerationConfig(null));
  const [renamingSession, setRenamingSession] = React.useState<GenerationSession | null>(null);
  const [deletingSession, setDeletingSession] = React.useState<GenerationSession | null>(null);
  const threadRef = React.useRef<HTMLDivElement | null>(null);
  const firstFrameInputRef = React.useRef<HTMLInputElement | null>(null);
  const referenceImageInputRef = React.useRef<HTMLInputElement | null>(null);

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

  const providerById = React.useMemo(
    () => new Map((providers.data ?? []).filter((profile) => profile.enabled).map((profile) => [profile.id, profile])),
    [providers.data],
  );
  const modelOptions = React.useMemo(
    () => buildGenerationEngineOptions(models.data ?? [], providers.data ?? [], defaults.data ?? []),
    [models.data, providers.data, defaults.data],
  );
  const optionByValue = React.useMemo(
    () => new Map(modelOptions.map((option) => [option.value, option])),
    [modelOptions],
  );
  const sessionOption =
    activeSession?.provider_profile_id && activeSession.model && activeSession.kind
      ? findGenerationOption(modelOptions, activeSession.provider_profile_id, activeSession.kind, activeSession.model)
      : null;
  const defaultImageOption = defaultGenerationOption(modelOptions, defaults.data ?? [], "image");
  const selectedModel = (modelId ? optionByValue.get(modelId) : null) ?? sessionOption ?? defaultImageOption ?? modelOptions[0] ?? null;
  const selectedAdapterAvailable = selectedModel?.adapter_available ?? false;
  const selectedImageSizes = imageSizeOptions(selectedModel);
  const selectedDurations = durationOptions(selectedModel);
  const selectedResolutions = videoResolutionOptions(selectedModel);
  const selectedAspectRatios = aspectRatioOptions(selectedModel);
  const supportsNegativePrompt = supportsParameter(selectedModel, "negative_prompt");
  const supportsReferenceImage = selectedModel?.kind === "image" && supportsParameter(selectedModel, "reference_image");
  const supportsFirstFrame = selectedModel?.kind === "video" && supportsParameter(selectedModel, "first_frame");
  React.useEffect(() => {
    setModelId(null);
  }, [activeSession?.id]);
  React.useEffect(() => {
    setGenerationConfig(defaultGenerationConfig(selectedModel));
  }, [selectedModel?.value]);
  const modelGroups = React.useMemo(() => {
    const grouped = new Map<string, GenerationEngineOption[]>();
    for (const model of modelOptions) {
      grouped.set(model.kind, [...(grouped.get(model.kind) ?? []), model]);
    }
    return ["image", "video", ...[...grouped.keys()].filter((kind) => kind !== "image" && kind !== "video")]
      .filter((kind) => (grouped.get(kind) ?? []).length > 0)
      .map((kind) => ({ kind, models: grouped.get(kind) ?? [] }));
  }, [modelOptions]);
  const capabilityLabel = (kind: string) => (kind === "image" ? t("capImage") : kind === "video" ? t("capVideo") : kind);
  const selectedCapabilityMissing = selectedModel ? !providerById.has(selectedModel.provider_profile_id) : false;
  const setConfigValue = (key: keyof GenerationConfig, value: string) =>
    setGenerationConfig((current) => ({ ...current, [key]: value }));
  const setFirstFrameUrl = (value: string) =>
    setGenerationConfig((current) => ({
      ...current,
      firstFrameUrl: value,
      firstFrameAssetId: value.trim() ? "" : current.firstFrameAssetId,
      firstFrameAssetName: value.trim() ? "" : current.firstFrameAssetName,
    }));
  const clearFirstFrameAsset = () =>
    setGenerationConfig((current) => ({ ...current, firstFrameAssetId: "", firstFrameAssetName: "" }));
  const setReferenceImageAsset = (asset: Asset) =>
    setGenerationConfig((current) => ({
      ...current,
      referenceImageAssetId: asset.id,
      referenceImageAssetName: asset.name,
      usePreviousImage: false,
    }));
  const clearReferenceImage = () =>
    setGenerationConfig((current) => ({
      ...current,
      referenceImageAssetId: "",
      referenceImageAssetName: "",
      usePreviousImage: false,
    }));
  const usePreviousImageAsReference = () =>
    setGenerationConfig((current) => ({
      ...current,
      referenceImageAssetId: "",
      referenceImageAssetName: "",
      usePreviousImage: true,
    }));
  const selectEngine = (value: string) => {
    const option = optionByValue.get(value);
    if (!option) return;
    setModelId(value);
    if (activeSession) {
      updateSessionEngine.mutate({
        id: activeSession.id,
        provider_profile_id: option.provider_profile_id,
        model: option.model,
        kind: option.kind,
      });
    }
  };

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
  const uploadFirstFrame = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, file, name: file.name }),
    onSuccess: (asset: Asset) => {
      setGenerationConfig((current) => ({
        ...current,
        firstFrameUrl: "",
        firstFrameAssetId: asset.id,
        firstFrameAssetName: asset.name,
      }));
      void qc.invalidateQueries({ queryKey: ["assets", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const uploadReferenceImage = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, file, name: file.name }),
    onSuccess: (asset: Asset) => {
      setReferenceImageAsset(asset);
      void qc.invalidateQueries({ queryKey: ["assets", workspace.id] });
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const ordered = React.useMemo(() => sessionJobs.data ?? [], [sessionJobs.data]);
  const latestImageResult = React.useMemo(
    () => [...ordered].reverse().find((generation) => generation.kind === "image" && generation.result_asset_id) ?? null,
    [ordered],
  );
  const effectiveReferenceImageAssetId =
    selectedModel?.kind === "image"
      ? generationConfig.referenceImageAssetId ||
        (generationConfig.usePreviousImage ? latestImageResult?.result_asset_id ?? "" : "")
      : "";
  const effectiveReferenceImageName =
    generationConfig.referenceImageAssetName ||
    (effectiveReferenceImageAssetId && latestImageResult?.result_asset_id === effectiveReferenceImageAssetId
      ? t("genPreviousImage")
      : "");

  const createGeneration = useMutation({
    mutationFn: async () => {
      let targetSessionId = activeSession?.id;
      if (!targetSessionId) {
        const payload: Record<string, string> = {
          workspace_id: workspace.id,
          title: prompt.trim().slice(0, 40) || "新生成",
        };
        if (modelId && selectedModel) {
          payload.provider_profile_id = selectedModel.provider_profile_id;
          payload.model = selectedModel.model;
          payload.kind = selectedModel.kind;
        }
        const created = await api<GenerationSession>("/api/generation/sessions", {
          method: "POST",
          body: JSON.stringify(payload),
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
          provider_profile_id: selectedModel!.provider_profile_id,
          provider: selectedModel!.provider,
          model: selectedModel!.model,
          kind: selectedModel!.kind,
          prompt,
          negative_prompt: supportsNegativePrompt ? generationConfig.negativePrompt.trim() : "",
          parameters: generationParameters(selectedModel!, generationConfig),
          source_asset_ids:
            selectedModel!.kind === "video" && supportsFirstFrame && generationConfig.firstFrameAssetId
              ? [generationConfig.firstFrameAssetId]
              : selectedModel!.kind === "image" && supportsReferenceImage && effectiveReferenceImageAssetId
                ? [effectiveReferenceImageAssetId]
                : [],
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
  const updateSessionEngine = useMutation({
    mutationFn: ({
      id,
      provider_profile_id,
      model,
      kind,
    }: {
      id: string;
      provider_profile_id: string;
      model: string;
      kind: string;
    }) =>
      api<GenerationSession>(`/api/generation/sessions/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ provider_profile_id, model, kind }),
      }),
    onSuccess: () => {
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
    if (!prompt.trim() || !selectedModel || !selectedAdapterAvailable || createGeneration.isPending) return;
    createGeneration.mutate();
  };

  return (
    <div className="gen-workspace">
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

      <section className="gen-main panel">
        <div className="gen-thread" ref={threadRef}>
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
        <form className="gen-composer" onSubmit={submit}>
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
              {selectedModel && <span className="composer-model">{selectedModel.label}</span>}
            </div>
            <Button
              type="submit"
              size="icon"
              className="chat-send"
              aria-label={t("generate")}
              disabled={!prompt.trim() || !selectedModel || !selectedAdapterAvailable || createGeneration.isPending}
            >
              {createGeneration.isPending ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
            </Button>
          </div>
        </form>
      </section>

      <aside className="gen-settings panel">
        <div className="panel-head">
          <h2>{t("generationEngineSettings")}</h2>
        </div>
        {selectedModel && selectedCapabilityMissing && (
          <ConfigNotice
            message={t("aiCapabilityNotConfigured").replace("{capability}", capabilityLabel(selectedModel.kind))}
            actionLabel={t("wfGoConfigure")}
            section={`providers:${selectedModel.kind}`}
          />
        )}
        {selectedModel && !selectedAdapterAvailable && (
          <div className="generation-engine-warning">
            <CircleAlert size={13} />
            {t("generationAdapterUnavailable").replace("{engine}", `${selectedModel.provider} · ${selectedModel.model}`)}
          </div>
        )}
        {selectedModel && (
          <>
            <label className="generation-setting">
              <span>{t("wfModelPreset")}</span>
              <Select value={selectedModel.value} onValueChange={selectEngine}>
                <SelectTrigger className="generation-config-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="generation-model-menu">
                  {modelGroups.map((group) => (
                    <React.Fragment key={group.kind}>
                      <div className="generation-model-select-group">{capabilityLabel(group.kind)}</div>
                      {group.models.map((model) => (
                        <SelectItem key={model.value} value={model.value} className="generation-model-option-item">
                          <span className="generation-model-option">
                            {model.kind === "image" ? <ImagePlus size={12} /> : <Video size={12} />}
                            <span>{model.label}</span>
                          </span>
                        </SelectItem>
                      ))}
                    </React.Fragment>
                  ))}
                </SelectContent>
              </Select>
            </label>
            {selectedModel.kind === "image" ? (
              <>
                {supportsParameter(selectedModel, "size") && selectedImageSizes.length > 0 && (
                  <label className="generation-setting">
                    <span>{t("genSize")}</span>
                    <Select value={generationConfig.size} onValueChange={(value) => setConfigValue("size", value)}>
                      <SelectTrigger className="generation-config-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedImageSizes.map((size) => (
                          <SelectItem key={size} value={size}>
                            {size}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                )}
                {supportsParameter(selectedModel, "num_images") && (
                  <label className="generation-setting">
                    <span>{t("genNumImages")}</span>
                    <input
                      className="generation-config-input"
                      type="number"
                      min={1}
                      max={maxImages(selectedModel)}
                      value={generationConfig.numImages}
                      onChange={(event) => setConfigValue("numImages", event.target.value)}
                    />
                  </label>
                )}
                {supportsParameter(selectedModel, "seed") && (
                  <label className="generation-setting">
                    <span>{t("genSeed")}</span>
                    <input
                      className="generation-config-input"
                      type="number"
                      placeholder="auto"
                      value={generationConfig.seed}
                      onChange={(event) => setConfigValue("seed", event.target.value)}
                    />
                  </label>
                )}
                {supportsNegativePrompt && (
                  <label className="generation-setting">
                    <span>{t("genNegativePrompt")}</span>
                    <input
                      className="generation-config-input"
                      value={generationConfig.negativePrompt}
                      onChange={(event) => setConfigValue("negativePrompt", event.target.value)}
                    />
                  </label>
                )}
                {supportsReferenceImage && (
                  <div className="generation-setting">
                    <span>{t("genReferenceImage")}</span>
                    <input
                      ref={referenceImageInputRef}
                      className="sr-only"
                      type="file"
                      accept="image/*"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (file) uploadReferenceImage.mutate(file);
                      }}
                    />
                    <div className="generation-reference-actions">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="generation-first-frame-upload"
                        onClick={() => referenceImageInputRef.current?.click()}
                        disabled={uploadReferenceImage.isPending}
                      >
                        {uploadReferenceImage.isPending ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
                        {uploadReferenceImage.isPending ? t("genFirstFrameUploading") : t("genReferenceImageUpload")}
                      </Button>
                      {latestImageResult?.result_asset_id && !generationConfig.usePreviousImage && !generationConfig.referenceImageAssetId && (
                        <Button type="button" variant="ghost" size="sm" onClick={usePreviousImageAsReference}>
                          {t("genUsePreviousImage")}
                        </Button>
                      )}
                    </div>
                    {effectiveReferenceImageAssetId && (
                      <div className="generation-first-frame-preview">
                        <button
                          type="button"
                          className="generation-first-frame-thumb"
                          onClick={() =>
                            openImagePreview({
                              src: assetFileUrl(effectiveReferenceImageAssetId),
                              title: effectiveReferenceImageName || t("genReferenceImage"),
                            })
                          }
                        >
                          <img src={assetThumbnailUrl(effectiveReferenceImageAssetId)} alt="" />
                        </button>
                        <span title={effectiveReferenceImageName || t("genReferenceImage")}>
                          {effectiveReferenceImageName || t("genReferenceImage")}
                        </span>
                        <Button type="button" variant="ghost" size="icon" onClick={clearReferenceImage} aria-label={t("delete")}>
                          <X size={13} />
                        </Button>
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <>
                {supportsParameter(selectedModel, "duration_seconds") && (
                  <label className="generation-setting">
                    <span>{t("genDuration")}</span>
                    {selectedDurations.length > 1 ? (
                      <Select value={generationConfig.durationSeconds} onValueChange={(value) => setConfigValue("durationSeconds", value)}>
                        <SelectTrigger className="generation-config-select">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {selectedDurations.map((duration) => (
                            <SelectItem key={duration} value={String(duration)}>
                              {duration}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <input
                        className="generation-config-input"
                        type="number"
                        min={1}
                        max={capabilityNumber(selectedModel, "max_duration_seconds", 10)}
                        value={generationConfig.durationSeconds}
                        onChange={(event) => setConfigValue("durationSeconds", event.target.value)}
                      />
                    )}
                  </label>
                )}
                {supportsParameter(selectedModel, "resolution") && selectedResolutions.length > 0 && (
                  <label className="generation-setting">
                    <span>{t("genResolution")}</span>
                    <Select value={generationConfig.resolution} onValueChange={(value) => setConfigValue("resolution", value)}>
                      <SelectTrigger className="generation-config-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedResolutions.map((resolution) => (
                          <SelectItem key={resolution} value={resolution}>
                            {resolution}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                )}
                {supportsParameter(selectedModel, "aspect_ratio") && selectedAspectRatios.length > 0 && (
                  <label className="generation-setting">
                    <span>{t("genAspectRatio")}</span>
                    <Select value={generationConfig.aspectRatio} onValueChange={(value) => setConfigValue("aspectRatio", value)}>
                      <SelectTrigger className="generation-config-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedAspectRatios.map((ratio) => (
                          <SelectItem key={ratio} value={ratio}>
                            {ratio}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                )}
                {supportsFirstFrame && (
                  <div className="generation-setting">
                    <span>{t("genFirstFrame")}</span>
                    <input
                      ref={firstFrameInputRef}
                      className="sr-only"
                      type="file"
                      accept="image/*"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (file) uploadFirstFrame.mutate(file);
                      }}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="generation-first-frame-upload"
                      onClick={() => firstFrameInputRef.current?.click()}
                      disabled={uploadFirstFrame.isPending}
                    >
                      {uploadFirstFrame.isPending ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
                      {uploadFirstFrame.isPending ? t("genFirstFrameUploading") : t("genFirstFrameUpload")}
                    </Button>
                    {generationConfig.firstFrameAssetId && (
                      <div className="generation-first-frame-preview">
                        <button
                          type="button"
                          className="generation-first-frame-thumb"
                          onClick={() =>
                            openImagePreview({
                              src: assetFileUrl(generationConfig.firstFrameAssetId),
                              title: generationConfig.firstFrameAssetName || t("genFirstFrame"),
                            })
                          }
                        >
                          <img src={assetThumbnailUrl(generationConfig.firstFrameAssetId)} alt="" />
                        </button>
                        <span title={generationConfig.firstFrameAssetName}>{generationConfig.firstFrameAssetName}</span>
                        <Button type="button" variant="ghost" size="icon" onClick={clearFirstFrameAsset} aria-label={t("delete")}>
                          <X size={13} />
                        </Button>
                      </div>
                    )}
                  </div>
                )}
                {supportsFirstFrame && (
                  <label className="generation-setting">
                    <span>{t("genFirstFrameUrl")}</span>
                    <Input
                      className="generation-config-input"
                      placeholder="https://..."
                      value={generationConfig.firstFrameUrl}
                      onChange={(event) => setFirstFrameUrl(event.target.value)}
                    />
                  </label>
                )}
              </>
            )}
          </>
        )}
      </aside>
    </div>
  );
}

function GenerationTurn({ generation, job }: { generation: GenerationJob; job: Job | null }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const status = job?.status ?? "queued";
  return (
    <article className="generation-turn-card">
      <div className="generation-turn-prompt">{String(generation.request.prompt ?? "")}</div>
      <div className="gen-turn">
        {generation.result_asset_id && generation.kind === "video" ? (
          <video
            className="gen-turn-video"
            src={assetFileUrl(generation.result_asset_id)}
            poster={assetThumbnailUrl(generation.result_asset_id)}
            controls
            preload="metadata"
          />
        ) : generation.result_asset_id ? (
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
    </article>
  );
}
