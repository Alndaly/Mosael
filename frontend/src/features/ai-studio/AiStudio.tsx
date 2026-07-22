import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CircleAlert,
  Copy,
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
import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/layout/EmptyState";
import { ConfigNotice } from "@/components/layout/ConfigNotice";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useImagePreview } from "@/components/app/image-preview";
import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";
import { generationSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { elapsedSecondsBetween, formatElapsedSeconds, relativeTime } from "@/lib/time";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

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
    <div className="inline-flex h-7 items-stretch overflow-hidden rounded-full border border-border bg-panel [&>button+button]:border-l [&>button+button]:border-border" role="tablist">
      <button
        type="button"
        role="tab"
        aria-selected={tab === "chat"}
        className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tab === "chat" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
        onClick={() => setTab("chat")}
      >
        {t("aiTabChat")}
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={tab === "generate"}
        className={cn("inline-flex cursor-pointer items-center gap-1 rounded-none border-0 bg-transparent px-[11px] py-[3px] text-xs text-muted-foreground transition-[background,color] duration-[120ms] hover:bg-secondary hover:text-foreground", tab === "generate" && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground")}
        onClick={() => setTab("generate")}
      >
        {t("aiTabGenerate")}
      </button>
    </div>
  );

  return (
    // 聊天/生成只在线程内部滚动,页面本身不滚(overflow-hidden)。
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-auto p-3.5 [&>*]:shrink-0 gap-0 overflow-hidden">
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
    <div className="grid min-h-0 flex-1 grid-cols-[240px_minmax(0,1fr)_300px] grid-rows-[minmax(0,1fr)] gap-2 max-[1180px]:grid-cols-[220px_minmax(0,1fr)] max-[820px]:grid-cols-[minmax(0,1fr)]">
      <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-rows-[auto_minmax(0,1fr)] max-[820px]:hidden">
        <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
          <h2>{t("generationSessionsTitle")}</h2>
          <Button variant="outline" size="sm" onClick={() => createSession.mutate()} disabled={createSession.isPending}>
            <Plus size={13} /> {t("generationNewSession")}
          </Button>
        </div>
        <div
          className={cn(
            "grid content-start gap-1 overflow-auto p-1.5 [scrollbar-gutter:stable] [scrollbar-width:none] hover:[scrollbar-color:color-mix(in_srgb,var(--muted-foreground)_35%,transparent)_transparent] hover:[scrollbar-width:thin] focus-within:[scrollbar-color:color-mix(in_srgb,var(--muted-foreground)_35%,transparent)_transparent] focus-within:[scrollbar-width:thin] [&::-webkit-scrollbar]:h-0 [&::-webkit-scrollbar]:w-0 hover:[&::-webkit-scrollbar]:h-1.5 hover:[&::-webkit-scrollbar]:w-1.5 focus-within:[&::-webkit-scrollbar]:h-1.5 focus-within:[&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]",
            sessions.isSuccess && (sessions.data ?? []).length === 0 && "content-center justify-items-center",
          )}
        >
          {sessions.isSuccess && (sessions.data ?? []).length === 0 && (
            <div className="grid justify-items-center gap-1.5 p-2.5 text-center text-xs text-muted-foreground">
              <MessageSquarePlus size={16} className="text-primary opacity-70" />
              <span>{t("generationNoSessions")}</span>
            </div>
          )}
          {(sessions.data ?? []).map((item) => (
            <ContextMenu key={item.id}>
              <ContextMenuTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    "grid w-full cursor-pointer gap-px rounded-md border-0 bg-transparent px-2 py-1.5 text-left transition-colors duration-100 hover:bg-muted",
                    activeSession?.id === item.id && "bg-accent shadow-[inset_2px_0_0_var(--primary)] hover:bg-accent",
                  )}
                  onClick={() => {
                    setSessionId(item.id);
                    window.localStorage.setItem(sessionKey, item.id);
                  }}
                >
                  <strong className="truncate text-xs font-semibold">{item.title}</strong>
                </button>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => setRenamingSession(item)}>
                  <Pencil /> {t("rename")}
                </ContextMenuItem>
                <ContextMenuSeparator />
                <ContextMenuItem className="text-destructive focus:text-destructive" onSelect={() => setDeletingSession(item)}>
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

      <section className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid min-w-0 grid-rows-[minmax(0,1fr)_auto]">
        <div className="flex flex-col gap-3.5 overflow-y-auto px-4 pb-2.5 pt-7" ref={threadRef}>
          {ordered.length === 0 && (
            <div className="m-auto">
              <EmptyState icon={<Sparkles size={22} />} title={t("noGenerationJobs")} body={t("promptPlaceholder")} />
            </div>
          )}
          {ordered.map((generation) => (
            <GenerationTurn
              key={generation.id}
              generation={generation}
              job={jobs.data?.find((item) => item.id === generation.job_id) ?? null}
            />
          ))}
        </div>
        <form
          className="mx-auto mb-3.5 mt-1.5 flex w-[min(780px,calc(100%-32px))] flex-col gap-1 rounded-[22px] border border-input bg-panel px-2.5 pb-1.5 pl-3 pt-2.5 shadow-[var(--shadow-raised)] transition-[border-color,box-shadow] duration-100 focus-within:border-ring focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_35%,transparent)]"
          onSubmit={submit}
        >
          <Textarea
            rows={2}
            className="max-h-[220px] min-h-11 w-full min-w-0 resize-none border-0 bg-transparent px-0 py-0.5 pb-1.5 text-[13.5px] leading-[1.55] shadow-none outline-none focus-visible:ring-0"
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
          <div className="flex items-center justify-between gap-1.5 pt-0.5">
            <div className="flex items-center gap-1.5">
              {switcher}
              {selectedModel && (
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-border px-[9px] py-0.5 text-[11.5px] text-muted-foreground">
                  {selectedModel.label}
                </span>
              )}
            </div>
            <Button
              type="submit"
              size="icon"
              className="shrink-0 rounded-full"
              aria-label={t("generate")}
              disabled={!prompt.trim() || !selectedModel || !selectedAdapterAvailable || createGeneration.isPending}
            >
              {createGeneration.isPending ? <Loader2 size={15} className="animate-mibu-spin" /> : <Send size={15} />}
            </Button>
          </div>
        </form>
      </section>

      <aside className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] flex min-w-0 flex-col gap-[9px] overflow-y-auto px-3 pb-3.5 max-[1180px]:col-span-full max-[1180px]:grid max-[1180px]:max-h-[220px] max-[1180px]:grid-cols-2 max-[1180px]:content-start max-[820px]:grid-cols-1">
        <div className="-mx-3 flex min-h-[38px] items-center justify-between border-b border-border px-3 py-2.5 max-[1180px]:col-span-full [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">
          <h2 className="text-xs tracking-[0.02em] text-muted-foreground">{t("generationEngineSettings")}</h2>
        </div>
        {selectedModel && selectedCapabilityMissing && (
          <ConfigNotice
            message={t("aiCapabilityNotConfigured").replace("{capability}", capabilityLabel(selectedModel.kind))}
            actionLabel={t("wfGoConfigure")}
            section={`providers:${selectedModel.kind}`}
            className="items-center gap-[7px] rounded-lg px-[9px] py-2 text-[11.5px] leading-[1.45]"
            textClassName="line-clamp-2"
            actionClassName="self-center"
          />
        )}
        {selectedModel && !selectedAdapterAvailable && (
          <div className="flex items-center gap-1.5 text-[11.5px] text-destructive">
            <CircleAlert size={13} />
            {t("generationAdapterUnavailable").replace("{engine}", `${selectedModel.provider} · ${selectedModel.model}`)}
          </div>
        )}
        {selectedModel && (
          <>
            <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
              <span>{t("wfModelPreset")}</span>
              <Select value={selectedModel.value} onValueChange={selectEngine}>
                <SelectTrigger className="h-8 w-full rounded-lg border-border bg-panel text-[12.5px] font-medium text-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="max-h-[min(320px,var(--radix-select-content-available-height))] w-[var(--radix-select-trigger-width)] p-1.5">
                  {modelGroups.map((group) => (
                    <React.Fragment key={group.kind}>
                      <div className="px-2 pb-1 pt-[7px] text-[10.5px] font-bold leading-none text-muted-foreground">
                        {capabilityLabel(group.kind)}
                      </div>
                      {group.models.map((model) => (
                        <SelectItem key={model.value} value={model.value} className="min-h-[30px] px-2 py-[5px]">
                          <span className="flex w-full min-w-0 items-center gap-[7px] leading-none [&_svg]:block [&_svg]:shrink-0 [&_svg]:text-muted-foreground">
                            {model.kind === "image" ? <ImagePlus size={12} /> : <Video size={12} />}
                            <span className="truncate">{model.label}</span>
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
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genSize")}</span>
                    <Select value={generationConfig.size} onValueChange={(value) => setConfigValue("size", value)}>
                      <SelectTrigger className="h-8 w-full rounded-lg border-border bg-panel text-[12.5px] font-medium text-foreground">
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
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genNumImages")}</span>
                    <Input
                      className="h-8 w-full min-w-0 rounded-lg border-border bg-panel px-2.5 text-[12.5px] font-medium text-foreground focus-visible:border-primary focus-visible:ring-primary/20"
                      type="number"
                      min={1}
                      max={maxImages(selectedModel)}
                      value={generationConfig.numImages}
                      onChange={(event) => setConfigValue("numImages", event.target.value)}
                    />
                  </label>
                )}
                {supportsParameter(selectedModel, "seed") && (
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genSeed")}</span>
                    <Input
                      className="h-8 w-full min-w-0 rounded-lg border-border bg-panel px-2.5 text-[12.5px] font-medium text-foreground focus-visible:border-primary focus-visible:ring-primary/20"
                      type="number"
                      placeholder="auto"
                      value={generationConfig.seed}
                      onChange={(event) => setConfigValue("seed", event.target.value)}
                    />
                  </label>
                )}
                {supportsNegativePrompt && (
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genNegativePrompt")}</span>
                    <Input
                      className="h-8 w-full min-w-0 rounded-lg border-border bg-panel px-2.5 text-[12.5px] font-medium text-foreground focus-visible:border-primary focus-visible:ring-primary/20"
                      value={generationConfig.negativePrompt}
                      onChange={(event) => setConfigValue("negativePrompt", event.target.value)}
                    />
                  </label>
                )}
                {supportsReferenceImage && (
                  <div className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
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
                    <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="w-full justify-center"
                        onClick={() => referenceImageInputRef.current?.click()}
                        disabled={uploadReferenceImage.isPending}
                      >
                        {uploadReferenceImage.isPending ? <Loader2 size={13} className="animate-mibu-spin" /> : <Upload size={13} />}
                        {uploadReferenceImage.isPending ? t("genFirstFrameUploading") : t("genReferenceImageUpload")}
                      </Button>
                      {latestImageResult?.result_asset_id && !generationConfig.usePreviousImage && !generationConfig.referenceImageAssetId && (
                        <Button type="button" variant="ghost" size="sm" onClick={usePreviousImageAsReference}>
                          {t("genUsePreviousImage")}
                        </Button>
                      )}
                    </div>
                    {effectiveReferenceImageAssetId && (
                      <div className="grid min-h-11 grid-cols-[44px_minmax(0,1fr)_28px] items-center gap-2 rounded-lg border border-border bg-[color-mix(in_srgb,var(--panel)_88%,var(--muted)_12%)] p-[5px]">
                        <button
                          type="button"
                          className="block size-auto h-[34px] w-11 cursor-zoom-in overflow-hidden rounded-lg border border-border bg-muted p-0"
                          onClick={() =>
                            openImagePreview({
                              src: assetFileUrl(effectiveReferenceImageAssetId),
                              title: effectiveReferenceImageName || t("genReferenceImage"),
                            })
                          }
                        >
                          <img className="block h-full w-full object-cover" src={assetThumbnailUrl(effectiveReferenceImageAssetId)} alt="" />
                        </button>
                        <span
                          className="truncate text-xs font-semibold text-foreground"
                          title={effectiveReferenceImageName || t("genReferenceImage")}
                        >
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
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genDuration")}</span>
                    {selectedDurations.length > 1 ? (
                      <Select value={generationConfig.durationSeconds} onValueChange={(value) => setConfigValue("durationSeconds", value)}>
                        <SelectTrigger className="h-8 w-full rounded-lg border-border bg-panel text-[12.5px] font-medium text-foreground">
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
                      <Input
                        className="h-8 w-full min-w-0 rounded-lg border-border bg-panel px-2.5 text-[12.5px] font-medium text-foreground focus-visible:border-primary focus-visible:ring-primary/20"
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
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genResolution")}</span>
                    <Select value={generationConfig.resolution} onValueChange={(value) => setConfigValue("resolution", value)}>
                      <SelectTrigger className="h-8 w-full rounded-lg border-border bg-panel text-[12.5px] font-medium text-foreground">
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
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genAspectRatio")}</span>
                    <Select value={generationConfig.aspectRatio} onValueChange={(value) => setConfigValue("aspectRatio", value)}>
                      <SelectTrigger className="h-8 w-full rounded-lg border-border bg-panel text-[12.5px] font-medium text-foreground">
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
                  <div className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
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
                      className="w-full justify-center"
                      onClick={() => firstFrameInputRef.current?.click()}
                      disabled={uploadFirstFrame.isPending}
                    >
                      {uploadFirstFrame.isPending ? <Loader2 size={13} className="animate-mibu-spin" /> : <Upload size={13} />}
                      {uploadFirstFrame.isPending ? t("genFirstFrameUploading") : t("genFirstFrameUpload")}
                    </Button>
                    {generationConfig.firstFrameAssetId && (
                      <div className="grid min-h-11 grid-cols-[44px_minmax(0,1fr)_28px] items-center gap-2 rounded-lg border border-border bg-[color-mix(in_srgb,var(--panel)_88%,var(--muted)_12%)] p-[5px]">
                        <button
                          type="button"
                          className="block size-auto h-[34px] w-11 cursor-zoom-in overflow-hidden rounded-lg border border-border bg-muted p-0"
                          onClick={() =>
                            openImagePreview({
                              src: assetFileUrl(generationConfig.firstFrameAssetId),
                              title: generationConfig.firstFrameAssetName || t("genFirstFrame"),
                            })
                          }
                        >
                          <img className="block h-full w-full object-cover" src={assetThumbnailUrl(generationConfig.firstFrameAssetId)} alt="" />
                        </button>
                        <span className="truncate text-xs font-semibold text-foreground" title={generationConfig.firstFrameAssetName}>
                          {generationConfig.firstFrameAssetName}
                        </span>
                        <Button type="button" variant="ghost" size="icon" onClick={clearFirstFrameAsset} aria-label={t("delete")}>
                          <X size={13} />
                        </Button>
                      </div>
                    )}
                  </div>
                )}
                {supportsFirstFrame && (
                  <label className="grid gap-1.5 text-[11.5px] font-semibold text-muted-foreground">
                    <span>{t("genFirstFrameUrl")}</span>
                    <Input
                      className="h-8 w-full min-w-0 rounded-lg border-border bg-panel px-2.5 text-[12.5px] font-medium text-foreground focus-visible:border-primary focus-visible:ring-primary/20"
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
  const { locale } = usePreferences();
  const { openImagePreview } = useImagePreview();
  const status = job?.status ?? "queued";
  const timestamp = generation.created_at ?? job?.created_at ?? null;
  const timestampLabel = timestamp ? relativeTime(timestamp, locale) : "";
  const isRunning = status === "running";
  const isFinished = status === "succeeded" || status === "failed";
  const durationSeconds = isRunning
    ? elapsedSecondsBetween(timestamp, new Date())
    : isFinished
      ? elapsedSecondsBetween(timestamp, job?.updated_at ?? generation.updated_at)
      : null;
  const durationLabel =
    typeof durationSeconds === "number"
      ? t(isRunning ? "usageRunning" : "usageDuration").replace("{t}", formatElapsedSeconds(durationSeconds))
      : "";
  return (
    <article className="grid w-full max-w-[780px] shrink-0 gap-2.5 self-center">
      <div className="grid justify-items-end gap-1">
        <div className="w-fit max-w-[min(560px,82%)] justify-self-end whitespace-pre-wrap break-words rounded-lg rounded-br bg-secondary px-3 py-[9px] text-[13.5px] leading-[1.65] text-foreground">
          {String(generation.request.prompt ?? "")}
        </div>
        {timestamp ? (
          <time className="text-[11px] leading-tight text-muted-foreground" dateTime={timestamp}>
            {timestampLabel}
          </time>
        ) : null}
      </div>
      <div className="grid min-h-7 justify-items-start gap-[7px] pb-2 pt-0.5">
        {generation.result_asset_id && generation.kind === "video" ? (
          <video
            className="block max-h-[420px] w-full max-w-[min(560px,100%)] rounded-lg border border-border bg-[#05070a]"
            src={assetFileUrl(generation.result_asset_id)}
            poster={assetThumbnailUrl(generation.result_asset_id)}
            controls
            preload="metadata"
          />
        ) : generation.result_asset_id ? (
          <button
            type="button"
            className="inline-block max-w-[min(560px,100%)] cursor-zoom-in border-0 bg-transparent p-0 focus-visible:rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-ring"
            onClick={() =>
              openImagePreview({
                src: assetFileUrl(generation.result_asset_id!),
                title: String(generation.request.prompt ?? generation.model),
              })
            }
          >
            <img
              className="block w-auto max-w-[min(560px,100%)] rounded-lg border border-border"
              src={assetThumbnailUrl(generation.result_asset_id)}
              alt=""
              loading="lazy"
            />
          </button>
        ) : status === "failed" ? (
          <GenerationFailureCard error={job?.error ?? ""} />
        ) : (
          <span className="inline-flex items-center gap-1.5 py-2 text-[12.5px] text-muted-foreground">
            <Loader2 size={13} className="animate-mibu-spin" /> {status === "running" ? t("generating") : t("genQueued")}
          </span>
        )}
        <small className="flex flex-wrap items-center gap-2 justify-self-start text-[11.5px] text-muted-foreground [&_span+span:before]:mr-2 [&_span+span:before]:content-['·']">
          <span>
            {generation.provider} · {generation.model}
          </span>
          {durationLabel ? <span>{durationLabel}</span> : null}
        </small>
      </div>
    </article>
  );
}

function GenerationFailureCard({ error }: { error: string }) {
  const t = useI18n();
  const [copied, setCopied] = React.useState(false);
  const summary = React.useMemo(() => generationErrorSummary(error, t("genFailed")), [error, t]);
  const copy = () => {
    if (!error) return;
    void navigator.clipboard?.writeText(error);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="grid w-[min(560px,100%)] gap-2 rounded-lg border border-[color-mix(in_srgb,var(--destructive)_34%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_7%,var(--card))] px-3 py-2.5">
      <div className="flex min-w-0 items-start gap-2 text-destructive">
        <CircleAlert size={14} className="mt-0.5 shrink-0" />
        <div className="grid min-w-0 gap-0.5">
          <strong className="text-[12.5px] leading-[1.35] text-destructive">{t("generationFailedTitle")}</strong>
          <span className="[overflow-wrap:anywhere] text-[12.5px] leading-[1.55] text-[color-mix(in_srgb,var(--destructive)_82%,var(--foreground))]">
            {summary}
          </span>
        </div>
      </div>
      {error ? (
        <div className="flex items-start justify-between gap-2">
          <details className="min-w-0 text-[11.5px] text-muted-foreground">
            <summary className="w-fit cursor-pointer list-none after:ml-1 after:inline-block after:content-['›'] [&::-webkit-details-marker]:hidden">
              {t("generationErrorDetail")}
            </summary>
            <pre className="mt-[7px] max-h-40 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-[color-mix(in_srgb,var(--background)_72%,var(--card))] p-2 font-mono text-[11px] leading-normal text-muted-foreground">
              {error}
            </pre>
          </details>
          <Button type="button" variant="ghost" size="sm" className="h-6 shrink-0 px-[7px] text-[11px]" onClick={copy}>
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? t("copied") : t("copyMessage")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function generationErrorSummary(error: string, fallback: string): string {
  const text = error.trim();
  if (!text) return fallback;
  const bodyMatch = text.match(/body:\s*(\{.*\})\s*$/s);
  if (bodyMatch) {
    try {
      const parsed = JSON.parse(bodyMatch[1]) as { error?: { message?: unknown }; message?: unknown };
      const message = parsed.error?.message ?? parsed.message;
      if (typeof message === "string" && message.trim()) return trimErrorSummary(message);
    } catch {
      // Fall through to text cleanup.
    }
  }
  const messageMatch = text.match(/"message"\s*:\s*"([^"]+)"/);
  if (messageMatch?.[1]) return trimErrorSummary(messageMatch[1]);
  const beforeDetails = text
    .replace(/^失败\s*·\s*/i, "")
    .split(" For more information check:")[0]
    .split("; body:")[0]
    .trim();
  return trimErrorSummary(beforeDetails || fallback);
}

function trimErrorSummary(value: string): string {
  return value.replace(/\s+/g, " ").trim().slice(0, 150);
}
