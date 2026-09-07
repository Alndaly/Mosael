import { SceneList } from "./SceneList";
import { LoadingState } from "@/components/layout/LoadingState";
import { EmptyState } from "@/components/layout/EmptyState";
import { SceneBlender } from "./SceneBlender";
import { useCanvasInputMode } from "@/components/app/canvasInputMode";
import { readSceneSnap, writeSceneSnap } from "./sceneSnap";
import { CanvasInputModeSwitch } from "@/components/app/CanvasInputModeSwitch";
import { useSceneFullscreen } from "./useSceneFullscreen";
import { SceneHistory } from "./SceneHistory";
import { SceneCameraPanel } from "./SceneCameraPanel";
import { SceneInspector } from "./SceneInspector";
import { Pick, Tool } from "./SceneControls";
import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Box,
  Camera,
  Image as ImageIcon,
  Check,
  CheckSquare,
  Download,
  Maximize,
  Minimize,
  ChevronRight,
  HelpCircle,
  Focus,
  History,
  Loader2,
  Magnet,
  Move,
  Pause,
  Play,
  Plus,
  RotateCcw,
  RotateCw,
  Scaling,
  Trash2,
  Sparkles,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import type { Workspace } from "@/api/client";
import { importAsset } from "@/api/domains/assets";
import { createBoard, updateBoard, type BoardItem } from "@/api/domains/boards";
import {
  createScene,
  deleteScene,
  getScene,
  listScenes,
  saveScene,
  uploadSceneModel,
  type Scene,
  type SceneContent,
  type SceneObject,
  type SceneShot,
} from "@/api/domains/scenes";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  CanvasAgentChat,
  type CanvasAgentMode,
} from "@/components/agent/CanvasAgentChat";
import { useAutosave } from "@/features/boards/useAutosave";
import {
  initialScene,
  makeObject,
  makeShot,
  objectLabels,
  removeObjects,
  uid,
} from "./sceneGraph";
import { SceneViewport, type ViewportHandle } from "./SceneViewport";
import "./scenes.css";

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const readId = () =>
  new URLSearchParams(location.hash.split("?")[1] ?? "").get("scene");
export function SceneStudio({ workspace }: { workspace: Workspace }) {
  const qc = useQueryClient(),
    [id, setId] = React.useState(readId),
    [creating, setCreating] = React.useState(false),
    [selecting, setSelecting] = React.useState(false);
  React.useEffect(() => {
    const read = () => setId(readId());
    addEventListener("hashchange", read);
    return () => removeEventListener("hashchange", read);
  }, []);
  const list = useQuery({
    queryKey: ["scenes", workspace.id],
    queryFn: () => listScenes(workspace.id),
  });
  const scene = useQuery({
    queryKey: ["scene", workspace.id, id],
    queryFn: () => getScene(workspace.id, id!),
    enabled: !!id,
  });
  async function create(demo: boolean) {
    setCreating(true);
    try {
      const s = await createScene(
        workspace.id,
        demo ? "三间展厅 · 运镜练习" : "未命名场景",
        initialScene(demo),
      );
      qc.setQueryData(["scene", workspace.id, s.id], s);
      await qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
      location.hash = `#/scenes?scene=${s.id}`;
    } catch (e) {
      toast.error(String(e));
    } finally {
      setCreating(false);
    }
  }
  if (id) {
    if (scene.isPending)
      return (
        <LoadingState label="正在打开场景…" />
      );
    if (scene.error)
      return (
        <div className="flex h-full min-h-0 flex-col overflow-auto">
          <EmptyState icon={<Box />} title="暂时无法打开场景" body={scene.error.message} action={<Button
            onClick={() => {
              location.hash = "#/scenes";
            }}
          >
            返回场景列表
          </Button>} />
        </div>
      );
    return (
      <SceneEditor
        key={`${workspace.id}:${id}`}
        initial={scene.data!}
        onBack={() => {
          location.hash = "#/scenes";
          void qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
        }}
      />
    );
  }
  return (
    <div className="scene-library">
      <header>
        <div>
          <h1>3D 场景</h1>
          <p>搭建空间，设计镜头，再把画面交给你选择的视频模型。</p>
        </div>
        <div className="scene-actions">
          {!!list.data?.length && <Button variant="outline" aria-pressed={selecting} onClick={() => setSelecting(!selecting)}><CheckSquare size={16} />{selecting ? "完成选择" : "选择"}</Button>}
          <Button
            variant="outline"
            disabled={creating}
            onClick={() => void create(true)}
          >
            打开三间展厅示例
          </Button>
          <Button disabled={creating} onClick={() => void create(false)}>
            <Plus size={16} />
            新建场景
          </Button>
        </div>
      </header>
      {list.isPending ? (
        <LoadingState className="h-auto flex-1" label="正在加载场景…" />
      ) : list.error ? (
        <div className="flex min-h-0 flex-1 flex-col" role="alert">
          <EmptyState icon={<Box />} title="暂时无法加载场景" body={list.error.message} action={<Button variant="secondary" onClick={() => void list.refetch()}>重试</Button>} />
        </div>
      ) : !list.data?.length ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <EmptyState icon={<Box />} title="从一个空间开始" body="添加几何体、导入模型，或从三间相连的展厅开始设计运镜。" action={<Button disabled={creating} onClick={() => void create(true)}>体验示例场景</Button>} />
        </div>
      ) : (
        <SceneList
          scenes={list.data}
          selecting={selecting}
          onSelecting={setSelecting}
          onOpen={sceneId => { location.hash = `#/scenes?scene=${sceneId}`; }}
          onRename={async (summary, name) => {
            try {
              const scene = await getScene(workspace.id, summary.id);
              await saveScene({ ...scene, name });
              await qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
              toast.success("场景已重命名");
              return true;
            } catch (e) { toast.error(String(e)); return false; }
          }}
          onDelete={async scenes => {
            const results = await Promise.allSettled(scenes.map(scene => deleteScene(workspace.id, scene.id)));
            const done = scenes.filter((_, i) => results[i].status === "fulfilled").map(scene => scene.id);
            for (const sceneId of done) {
              qc.removeQueries({ queryKey: ["scene", workspace.id, sceneId] });
              localStorage.removeItem(`mosael.scene-draft:${workspace.id}:${sceneId}`);
            }
            await qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
            if (done.length) toast.success(`已删除 ${done.length} 个场景`);
            const failure = results.find(r => r.status === "rejected");
            if (failure?.status === "rejected") toast.error(`部分场景未能删除：${String(failure.reason)}`);
            return done;
          }}
        />
      )}
    </div>
  );
}
function SceneEditor({
  initial,
  onBack,
}: {
  initial: Scene;
  onBack: () => void;
}) {
  const [navigation] = useCanvasInputMode();
  const studioRoot = React.useRef<HTMLDivElement>(null);
  const fullscreen = useSceneFullscreen(studioRoot);
  const qc = useQueryClient(),
    [draft, setDraft] = React.useState(() => ({
      name: initial.name,
      content: initial.content,
    })),
    current = React.useRef(draft);
  current.current = draft;
  const revision = React.useRef(initial.revision),
    saved = React.useRef(JSON.stringify(draft)),
    [error, setError] = React.useState(""),
    [history, setHistory] = React.useState<(typeof draft)[]>([]),
    [future, setFuture] = React.useState<(typeof draft)[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null),
    [mode, setMode] = React.useState<"translate" | "rotate" | "scale">(
      "translate",
    ),
    [step, setStep] = React.useState<"build" | "camera" | "output">("build"),
    [addOpen, setAddOpen] = React.useState(false),
    // 吸附是「我习惯这么干活」,不是这一次的临时状态 —— 和画布输入模式同一类,记住它。
    // 每次打开场景都退回关闭,等于让常开的人每次先点一下。
    [snap, setSnap] = React.useState(readSceneSnap),
    [shotId, setShotId] = React.useState(initial.content.shots[0].id),
    [time, setTime] = React.useState(0),
    [viewMode, setViewMode] = React.useState<"edit" | "camera" | "observe">(
      "edit",
    ),
    [playing, setPlaying] = React.useState(false),
    [busy, setBusy] = React.useState(""),
    [progress, setProgress] = React.useState(0),
    [agent, setAgent] = React.useState<CanvasAgentMode | null>(null),
    [revisions, setRevisions] = React.useState(false),
    [recovery, setRecovery] = React.useState<typeof draft | null>(null);
  const preview = viewMode === "camera";
  const observing = viewMode === "observe";
  const setPreview = (value: boolean) => setViewMode(value ? "camera" : "edit");
  function togglePlayback() {
    if (viewMode === "edit") setViewMode("camera");
    if (time >= shot.duration) setTime(0);
    setPlaying(!playing);
  }
  const view = React.useRef<ViewportHandle>(null),
    file = React.useRef<HTMLInputElement>(null),
    recordAbort = React.useRef<AbortController | null>(null),
    mounted = React.useRef(true);
  const cacheKey = `mosael.scene-draft:${initial.workspace_id}:${initial.id}`;
  React.useEffect(() => {
    mounted.current = true;
    try {
      const raw = localStorage.getItem(cacheKey);
      if (raw) {
        const cached = JSON.parse(raw);
        if (
          cached.name &&
          cached.content?.version === 1 &&
          JSON.stringify(cached) !== saved.current
        )
          setRecovery(cached);
      }
    } catch {
      /* A corrupt local draft must not prevent opening the server copy. */
    }
    return () => {
      mounted.current = false;
      recordAbort.current?.abort();
    };
  }, [cacheKey]);
  const autosave = useAutosave(draft, async (next) => {
    try {
      const result = await saveScene({
        ...initial,
        ...next,
        revision: revision.current,
      });
      revision.current = result.revision;
      saved.current = JSON.stringify(next);
      if (JSON.stringify(current.current) === saved.current)
        localStorage.removeItem(cacheKey);
      if (mounted.current) setError("");
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : String(e));
      throw e;
    }
  });
  function change(next: typeof draft) {
    setHistory((h) => [...h.slice(-49), current.current]);
    setFuture([]);
    current.current = next;
    setDraft(next);
    try {
      localStorage.setItem(cacheKey, JSON.stringify(next));
    } catch {
      toast.error("本地草稿空间不足，请及时保存或导出场景。");
    }
  }
  function update(content: SceneContent) {
    change({ ...current.current, content });
  }
  function objectPatch(id: string, patch: Partial<SceneObject>) {
    update({
      ...current.current.content,
      objects: current.current.content.objects.map((o) =>
        o.id === id ? { ...o, ...patch } : o,
      ),
    });
  }
  function undo() {
    if (!history.length) return;
    const next = history[history.length - 1];
    setFuture((f) => [current.current, ...f]);
    setHistory((h) => h.slice(0, -1));
    current.current = next;
    setDraft(next);
    localStorage.setItem(cacheKey, JSON.stringify(next));
  }
  function redo() {
    if (!future.length) return;
    const next = future[0];
    setHistory((h) => [...h, current.current]);
    setFuture((f) => f.slice(1));
    current.current = next;
    setDraft(next);
    localStorage.setItem(cacheKey, JSON.stringify(next));
  }
  React.useEffect(() => {
    let active = true;
    const timer = setInterval(async () => {
      if (JSON.stringify(current.current) !== saved.current) return;
      try {
        const result = await getScene(initial.workspace_id, initial.id);
        if (
          !active ||
          JSON.stringify(current.current) !== saved.current ||
          result.revision === revision.current
        )
          return;
        revision.current = result.revision;
        const next = { name: result.name, content: result.content };
        saved.current = JSON.stringify(next);
        current.current = next;
        setDraft(next);
        setHistory([]);
        setFuture([]);
      } catch {
        /* Leave the local draft intact while offline. */
      }
    }, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [initial.id, initial.workspace_id]);
  const shot =
      draft.content.shots.find((s) => s.id === shotId) ??
      draft.content.shots[0],
    object = draft.content.objects.find((o) => o.id === selected);
  function shotPatch(patch: Partial<SceneShot>) {
    update({
      ...current.current.content,
      shots: current.current.content.shots.map((s) =>
        s.id === shot.id ? { ...s, ...patch } : s,
      ),
    });
  }
  React.useEffect(() => {
    if (!playing) return;
    const start = performance.now() - time * 1000;
    let frame = 0;
    function tick() {
      const t = (performance.now() - start) / 1000;
      if (t >= shot.duration) {
        setTime(shot.duration);
        setPlaying(false);
        return;
      }
      setTime(t);
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, shot.id, shot.duration]);
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.defaultPrevented ||
        (e.target as HTMLElement).closest(
          "input,textarea,[contenteditable=true],[role=dialog]",
        ) ||
        busy
      )
        return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
      }
      if (
        (e.key === "Delete" || e.key === "Backspace") &&
        selected &&
        step === "build"
      ) {
        e.preventDefault();
        update(removeObjects(current.current.content, [selected]));
        setSelected(null);
      }
      if (e.key.toLowerCase() === "f" && !e.metaKey && !e.ctrlKey)
        view.current?.focus();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  function add(kind: SceneObject["kind"]) {
    if (draft.content.objects.length >= 500) {
      toast.error("单个场景最多 500 个对象");
      return;
    }
    const o = makeObject(kind);
    const halfWidth = ["sphere", "cylinder"].includes(kind)
      ? o.parameters.radius
      : o.parameters.width / 2;
    o.position = view.current?.placement(halfWidth) ?? [0, 0, 0];
    update({ ...draft.content, objects: [...draft.content.objects, o] });
    setSelected(o.id);
    setAddOpen(false);
    setPreview(false);
    requestAnimationFrame(() => view.current?.focus());
  }
  async function work(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setPlaying(false);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      if (mounted.current) {
        setBusy("");
        setProgress(0);
      }
    }
  }
  async function importModel(f: File) {
    await work("导入模型", async () => {
      const m = await uploadSceneModel(initial.workspace_id, initial.id, f);
      const o = makeObject("model", { name: m.name, model_id: m.id });
      update({
        ...current.current.content,
        objects: [...current.current.content.objects, o],
      });
      setSelected(o.id);
    });
  }
  async function assetFrame(t: number) {
    const blob = await view.current!.frame(shot, t);
    return importAsset({
      workspaceId: initial.workspace_id,
      file: new File([blob], `${draft.name}-${shot.name}-${t.toFixed(2)}.png`, {
        type: "image/png",
      }),
    });
  }
  async function exportVideo() {
    const controller = new AbortController();
    recordAbort.current = controller;
    const blob = await view
      .current!.record(shot, controller.signal, setProgress)
      .finally(() => {
        recordAbort.current = null;
      });
    const asset = await importAsset({
      workspaceId: initial.workspace_id,
      file: new File(
        [blob],
        `${draft.name}-${shot.name}.${blob.type === "video/mp4" ? "mp4" : "webm"}`,
        {
          type: blob.type,
        },
      ),
    });
    recordAbort.current = null;
    return asset;
  }
  async function bridge(kind: "image" | "frames" | "video") {
    await work("准备生成素材", async () => {
      const sources: NonNullable<
        NonNullable<BoardItem["form"]>["source_assets"]
      > = [];
      const items: BoardItem[] = [];
      if (kind === "image") {
        const a = await assetFrame(time);
        sources.push({ asset_id: a.id, role: "reference_image" });
      } else if (kind === "frames") {
        for (const [i, t] of [0, shot.duration].entries()) {
          const a = await assetFrame(t);
          sources.push({
            asset_id: a.id,
            role: i ? "last_frame" : "first_frame",
          });
          items.push({
            id: uid(),
            kind: "image",
            x: 0,
            y: i * 280,
            asset_id: a.id,
          });
        }
      } else {
        const a = await exportVideo();
        sources.push({ asset_id: a.id, role: "reference_video" });
        items.push({ id: uid(), kind: "video", x: 0, y: 0, asset_id: a.id });
      }
      const thumbnail =
        kind === "video" ? (await assetFrame(0)).id : sources[0].asset_id;
      items.push({
        id: uid(),
        kind: "scene",
        scene_id: initial.id,
        text: draft.name,
        asset_id: thumbnail,
        x: -440,
        y: 0,
      });
      const board = await createBoard({
        workspace_id: initial.workspace_id,
        name: `${draft.name} · ${shot.name}`,
      });
      const generatorId = uid();
      const edges = items
        .filter((i) => kind === "image" ? i.kind === "scene" : i.kind !== "scene")
        .map((i) => ({ id: uid(), source: i.id, target: generatorId }));
      items.push({
        id: generatorId,
        kind: kind === "image" ? "image" : "video",
        x: kind === "image" ? 0 : 460,
        y: 100,
        form: {
          prompt: kind === "image"
            ? `参考 3D 场景「${draft.name}」的画面构图、空间布局与摄像机视角，生成精细的图片。`
            : `参考 3D 场景「${draft.name}」的构图、空间布局和运镜，生成最终视频。`,
          source_assets: sources,
          mode: kind === "frames" ? "first_frame" : undefined,
          parameters: {
            aspect_ratio: shot.aspect,
            ...(kind !== "image" ? { duration_seconds: shot.duration } : {}),
          },
        },
      });
      await updateBoard(board.id, {
        workspace_id: initial.workspace_id,
        base_revision: board.revision,
        canvas: { items, edges },
      });
      await qc.invalidateQueries({
        queryKey: ["boards", initial.workspace_id],
      });
      location.hash = `#/boards?board=${board.id}`;
      toast.success(kind === "image" ? "场景画面已作为参考图，选择支持参考图的图片模型即可生成。" : "选择视频节点后，可自行选择模型和参数。");
    });
  }
  function recordView(at: number) {
    const frame = {
      ...view.current!.camera(),
      time: Math.min(shot.duration, Math.max(0, at)),
    };
    const frames = shot.frames.filter(
      (f) => Math.abs(f.time - frame.time) > 0.001,
    );
    if (frames.length >= 100) {
      toast.error("单个镜头最多 100 个途经点，请先移除一个。");
      return;
    }
    frames.push(frame);
    frames.sort((a, b) => a.time - b.time);
    shotPatch({ frames });
    setTime(frame.time);
    toast.success(
      frame.time === 0
        ? "已设置镜头起点"
        : frame.time === shot.duration
          ? "已设置镜头终点"
          : "已记录当前视角",
    );
  }
  return (
    <div
      ref={studioRoot}
      className="scene-studio"
      data-screen-mode={fullscreen.active ? "viewport" : undefined}
    >
      <header className="scene-header">
        <Tool label="返回场景列表" onClick={onBack}>
          <ArrowLeft size={17} />
        </Tool>
        <div className="scene-heading">
          <input
            className="scene-name"
            aria-label="场景名称"
            maxLength={160}
            value={draft.name}
            onChange={(e) => change({ ...draft, name: e.target.value })}
          />
          <span className="scene-save" role="status">
            {error ? (
              "未保存"
            ) : autosave.pending ? (
              "保存中…"
            ) : (
              <>
                <Check size={13} />
                已保存
              </>
            )}
          </span>
        </div>
        <div className="scene-actions">
          <Tool
            label="撤销"
            onClick={undo}
            disabled={!history.length || !!busy}
          >
            <RotateCcw size={16} />
          </Tool>
          <Tool label="重做" onClick={redo} disabled={!future.length || !!busy}>
            <RotateCw size={16} />
          </Tool>
          <Tool label="版本记录" onClick={() => setRevisions(true)}>
            <History size={16} />
          </Tool>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAgent(agent ? null : "docked")}
          >
            <Sparkles size={15} />
            建模助手
          </Button>
          <SceneBlender scene={initial} pending={autosave.pending || !!error} busy={!!busy} work={work} prepare={async () => {
            const snapshot = JSON.stringify(current.current);
            if (snapshot !== saved.current) throw new Error("请等待场景保存完成后重试。");
            const sourceRevision = revision.current;
            const blob = await view.current!.glb();
            if (snapshot !== JSON.stringify(current.current) || revision.current !== sourceRevision)
              throw new Error("场景在导出时发生变化，请重新发送。");
            return { revision: sourceRevision, shotId, blob };
          }} />
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" disabled={!!busy}>
                <Download size={15} />
                导出文件
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="scene-export">
              <button
                onClick={() =>
                  void work("导出模型", async () =>
                    download(await view.current!.glb(), `${draft.name}.glb`),
                  )
                }
              >
                导出 3D 模型 · GLB
              </button>
              <button
                onClick={() =>
                  download(
                    new Blob([JSON.stringify(draft, null, 2)], {
                      type: "application/json",
                    }),
                    `${draft.name}.json`,
                  )
                }
              >
                导出场景描述 · JSON
              </button>
              <button
                onClick={() =>
                  void work("保存镜头画面", async () => {
                    await assetFrame(time);
                    toast.success("画面已保存到素材库");
                  })
                }
              >
                当前镜头画面 → 素材库
              </button>
              <button
                onClick={() =>
                  void work("导出镜头预览", async () => {
                    await exportVideo();
                    toast.success("镜头预览已保存到素材库");
                  })
                }
              >
                镜头预览视频 → 素材库
              </button>
              <hr />
              <button onClick={() => void bridge("image")}>
                当前画面 → 图片生成
              </button>
              <button onClick={() => void bridge("frames")}>
                首尾帧 → 视频生成
              </button>
              <button onClick={() => void bridge("video")}>
                参考视频 → 视频生成
              </button>
              <p>进入画布后选择模型。生成模型不一定严格复现 3D 轨迹。</p>
            </PopoverContent>
          </Popover>
        </div>
      </header>
      {error && (
        <div className="scene-notice" role="alert">
          保存失败，草稿已保留：{error}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDraft({ ...current.current })}
          >
            重试
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              download(
                new Blob([JSON.stringify(draft, null, 2)], {
                  type: "application/json",
                }),
                `${draft.name}-草稿.json`,
              )
            }
          >
            导出草稿
          </Button>
        </div>
      )}
      {recovery && (
        <div className="scene-notice">
          发现未保存的本地草稿。
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              change(recovery);
              setRecovery(null);
            }}
          >
            恢复草稿
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setRecovery(null);
              localStorage.removeItem(cacheKey);
            }}
          >
            使用已保存版本
          </Button>
        </div>
      )}
      <nav className="scene-steps" aria-label="制作步骤">
        {(
          [
            ["build", "搭建场景", "添加物体和模型"],
            ["camera", "设计镜头", "构图与运镜"],
            ["output", "生成素材", "选择图片或视频"],
          ] as const
        ).map(([key, label, hint], i) => (
          <button
            key={key}
            title={hint}
            aria-current={step === key ? "step" : undefined}
            disabled={!!busy}
            onClick={() => {
              setStep(key);
              setPlaying(false);
              setPreview(key === "output");
            }}
          >
            <span className="scene-step-number">{i + 1}</span>
            <strong>{label}</strong>
          </button>
        ))}
      </nav>
      <div
        className="scene-workspace"
        data-step={step}
        data-agent={agent === "docked"}
      >
        <main className="scene-stage">
          <div className="scene-stage-bar">
            <div className="scene-segment" role="group" aria-label="观察方式">
              {(
                [
                  ["edit", "编辑视角"],
                  ["camera", "镜头画面"],
                  ["observe", "全局动线"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={viewMode === value}
                  onClick={() => setViewMode(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="scene-actions">
              {viewMode === "edit" && step === "build" && (
                <>
                  {(
                    [
                      ["translate", "移动", Move],
                      ["rotate", "旋转", RotateCw],
                      ["scale", "缩放", Scaling],
                    ] as const
                  ).map(([key, label, Icon]) => (
                    <button
                      key={key}
                      className="scene-labeled-tool"
                      aria-pressed={mode === key}
                      disabled={!selected}
                      onClick={() => setMode(key)}
                    >
                      <Icon size={15} />
                      {label}
                    </button>
                  ))}
                  {/* 吸附跟着这三个工具走:它改的正是它们的步长(位移 0.25 米、旋转 15°、
                      缩放 0.1,见 SceneViewport 的 setTranslationSnap 一带)。所以它和它们
                      同一排、同一种控件、同一个显示条件 —— 单拎到别处会读成一个无关的开关。
                      **不跟着 disabled**:没选中物体时它照样可以先打开,下一次拖动就生效。 */}
                  <button
                    className="scene-labeled-tool"
                    aria-pressed={snap}
                    title="吸附：位移 0.25 米 · 旋转 15° · 缩放 0.1"
                    onClick={() => setSnap((on) => writeSceneSnap(!on))}
                  >
                    <Magnet size={15} />
                    吸附
                  </button>
                </>
              )}
              {!preview && (
                <Popover>
                  <PopoverTrigger asChild>
                    <button className="scene-labeled-tool">
                      <Focus size={15} />
                      视角
                    </button>
                  </PopoverTrigger>
                  <PopoverContent className="scene-add" align="end">
                    {(
                      [
                        ["perspective", "整体视角"],
                        ["front", "正面"],
                        ["top", "俯视"],
                      ] as const
                    ).map(([key, label]) => (
                      <button key={key} onClick={() => view.current?.view(key)}>
                        {label}
                      </button>
                    ))}
                    <button onClick={() => view.current?.focus()}>
                      {observing ? "完整动线 · F" : "聚焦选中物体 · F"}
                    </button>
                  </PopoverContent>
                </Popover>
              )}
              <CanvasInputModeSwitch />
              <button
                className="scene-labeled-tool"
                aria-label={
                  fullscreen.active ? "退出视图全屏" : "视图全屏"
                }
                aria-pressed={fullscreen.active}
                onClick={() => void fullscreen.toggle()}
              >
                {fullscreen.active ? (
                  <Minimize size={15} />
                ) : (
                  <Maximize size={15} />
                )}
                {fullscreen.active ? "退出全屏" : "全屏"}
              </button>
              <Popover>
                <PopoverTrigger asChild>
                  <button className="scene-tool" aria-label="操作说明">
                    <HelpCircle size={16} />
                  </button>
                </PopoverTrigger>
                <PopoverContent className="scene-help" align="end">
                  <strong>如何操作画面</strong>
                  <p>
                    {navigation === "trackpad" ? (
                      <>
                        双指滑动：平移画面
                        <br />
                        双指捏合：拉近或拉远
                        <br />
                        Shift + 双指滑动：环绕观察
                        <br />
                        按住触控板拖动：环绕观察
                      </>
                    ) : (
                      <>
                        左键拖动：环绕观察
                        <br />
                        右键拖动：平移
                        <br />
                        滚轮：拉近或拉远
                      </>
                    )}
                  </p>
                  <p>点击物体选择 · F：找到选中的物体</p>
                  <p>
                    编辑视角用于调整构图；镜头画面展示最终取景；全局动线可在播放时观察摄像机位置与朝向。
                  </p>
                </PopoverContent>
              </Popover>
            </div>
          </div>
          <SceneViewport
            ref={view}
            workspace={initial.workspace_id}
            sceneId={initial.id}
            content={draft.content}
            selected={step === "build" ? selected : null}
            mode={mode}
            snap={snap}
            navigation={navigation}
            shot={shot}
            time={time}
            preview={preview}
            observing={observing}
            onCameraView={() => setViewMode("camera")}
            onSelect={(id) => {
              setSelected(id);
              if (step === "output") setStep("build");
            }}
            onTransform={objectPatch}
            onError={(message) => toast.error(message)}
          />
          {busy && (
            <div className="scene-busy">
              <Loader2 className="animate-spin" />
              <span>
                {busy}
                {progress > 0 ? ` ${Math.round(progress * 100)}%` : ""}
              </span>
              {recordAbort.current && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => recordAbort.current?.abort()}
                >
                  取消
                </Button>
              )}
            </div>
          )}
          {(step !== "build" || fullscreen.active) && (
            <section className="scene-timeline" aria-label="镜头播放控制">
              <div className="scene-shot-row">
                <Camera size={16} />
                <Pick
                  label="当前镜头"
                  value={shot.id}
                  options={draft.content.shots.map((s) => [s.id, s.name])}
                  onChange={(id) => {
                    setShotId(id);
                    setTime(0);
                    setPlaying(false);
                  }}
                />
                <Tool
                  label="新建镜头"
                  disabled={draft.content.shots.length >= 32}
                  onClick={() => {
                    const s = makeShot();
                    s.name = `镜头 ${draft.content.shots.length + 1}`;
                    s.frames = [view.current!.camera()];
                    update({
                      ...draft.content,
                      shots: [...draft.content.shots, s],
                    });
                    setShotId(s.id);
                    setTime(0);
                  }}
                >
                  <Plus size={16} />
                </Tool>
                <div className="scene-spacer" />
                <Button
                  variant="outline"
                  size="sm"
                  disabled={viewMode !== "edit" || !!busy}
                  onClick={() => recordView(time)}
                >
                  <Camera size={15} />
                  记录此视角
                </Button>
                <Tool
                  label={playing ? "暂停" : "播放镜头"}
                  disabled={!!busy}
                  onClick={togglePlayback}
                >
                  {playing ? <Pause size={17} /> : <Play size={17} />}
                </Tool>
                <span className="scene-time">
                  {time.toFixed(1)} / {shot.duration.toFixed(1)} s
                </span>
              </div>
              <input
                aria-label="镜头时间"
                type="range"
                min={0}
                max={shot.duration}
                step={0.01}
                value={Math.min(time, shot.duration)}
                onChange={(e) => {
                  setTime(Number(e.target.value));
                  setPlaying(false);
                }}
              />
              {/* **关键帧落在轨道上,位置即时间。** 此前是一排文字标签横向排开,几十个关键帧
                  就是几十个「途经点 · 0.7s」滚动着 —— 它们本来有时间坐标,却和上面的进度条
                  完全脱节,读者得靠念秒数把两者对起来。剪辑页的时间线就是靠位置表达时间的,
                  这里同理:一枚标记钉在它自己的时刻上,与进度条共用一条横轴。 */}
              <div
                className="scene-keyframe-track"
                role="group"
                aria-label={`${shot.name} 的关键帧`}
              >
                {shot.frames.map((f) => {
                  const at = shot.duration > 0 ? (f.time / shot.duration) * 100 : 0;
                  const edge = f.time === 0 ? "start" : f.time === shot.duration ? "end" : undefined;
                  return (
                    <button
                      key={f.time}
                      className="scene-keyframe"
                      style={{ left: `${at}%` }}
                      data-edge={edge}
                      aria-pressed={Math.abs(time - f.time) < 0.05}
                      title={`${edge === "start" ? "起点" : edge === "end" ? "终点" : "途经点"} · ${f.time.toFixed(1)}s`}
                      aria-label={`${edge === "start" ? "起点" : edge === "end" ? "终点" : "途经点"} ${f.time.toFixed(1)} 秒`}
                      onClick={() => {
                        setTime(f.time);
                        if (!observing) setPreview(true);
                        setPlaying(false);
                      }}
                    />
                  );
                })}
              </div>
            </section>
          )}
        </main>
        <aside className="scene-side">
          <div className="scene-side-scroll">
            {step === "build" && (
              <>
                <div className="scene-objects">
                  <header>
                    <h2>
                      场景中的物体 <span>{draft.content.objects.length}</span>
                    </h2>
                    <Popover open={addOpen} onOpenChange={setAddOpen}>
                      <PopoverTrigger asChild>
                        <Button size="sm" aria-label="添加物体">
                          <Plus size={15} />
                          添加
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent align="start" className="scene-add">
                        {(
                          [
                            "box",
                            "sphere",
                            "cylinder",
                            "plane",
                            "room",
                            "stairs",
                            "group",
                            "light",
                          ] as const
                        ).map((k) => (
                          <button key={k} onClick={() => add(k)}>
                            <Box size={15} />
                            {objectLabels[k]}
                          </button>
                        ))}
                        <button
                          onClick={() => {
                            setAddOpen(false);
                            file.current?.click();
                          }}
                        >
                          <Upload size={15} />
                          导入 GLB / glTF
                        </button>
                      </PopoverContent>
                    </Popover>
                  </header>
                  {!draft.content.objects.length && (
                    <div className="scene-start">
                      <Box size={28} strokeWidth={1.4} />
                      <strong>先放入一个物体</strong>
                      <p>点击「添加」选择形状，也可以导入已有的 3D 模型。</p>
                    </div>
                  )}
                  <div className="scene-object-list">
                    {draft.content.objects.map((o) => (
                      <div className="scene-object-row" key={o.id}>
                        <button
                          aria-pressed={selected === o.id}
                          onClick={() => {
                            setSelected(o.id);
                            setPreview(false);
                            requestAnimationFrame(() => view.current?.focus());
                          }}
                          onDoubleClick={() => view.current?.focus()}
                          style={{ paddingLeft: o.parent_id ? 24 : 10 }}
                        >
                          <Box size={14} />
                          <span>{o.name}</span>
                          {o.hidden && <small>隐藏</small>}
                        </button>
                        <button
                          className="scene-object-delete"
                          aria-label={`删除物体：${o.name}`}
                          title={`删除 ${o.name}`}
                          disabled={!!busy}
                          onClick={() => {
                            const content = removeObjects(
                              current.current.content,
                              [o.id],
                            );
                            update(content);
                            if (
                              !content.objects.some(
                                (item) => item.id === selected,
                              )
                            )
                              setSelected(null);
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                  <footer>
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full"
                      onClick={() => file.current?.click()}
                    >
                      <Upload size={14} />
                      导入模型
                    </Button>
                  </footer>
                  <input
                    ref={file}
                    type="file"
                    hidden
                    accept=".glb,.gltf"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void importModel(f);
                      e.target.value = "";
                    }}
                  />
                </div>

                <SceneInspector
                  content={draft.content}
                  object={object}
                  objectPatch={objectPatch}
                  update={update}
                  setSelected={setSelected}
                />
              </>
            )}
            {step === "camera" && (
              <SceneCameraPanel
                shot={shot}
                time={time}
                preview={viewMode !== "edit"}
                onPatch={shotPatch}
                onTime={setTime}
                onPreview={(value) => {
                  if (!value || !observing) setPreview(value);
                }}
                onPlaying={setPlaying}
                capture={recordView}
                observe={() => {
                  view.current?.editCamera(shot, time);
                  setPreview(false);
                  setPlaying(false);
                }}
                camera={() => view.current!.camera()}
              />
            )}
            {step === "output" && (
              <section className="scene-output-panel">
                <h2>基于场景生成图片或视频</h2>
                <p>用当前画面生成图片，或将构图与运镜交给视频模型。</p>
                <div className="scene-output-summary">
                  <span>{shot.name}</span>
                  <small>
                    {shot.duration} 秒 · {shot.aspect}
                  </small>
                </div>
                <button
                  className="scene-choice"
                  disabled={!!busy}
                  onClick={() => void bridge("image")}
                >
                  <ImageIcon size={20} />
                  <span>
                    <strong>使用当前画面生成图片</strong>
                    <small>
                      将当前镜头 {time.toFixed(1)} 秒的画面作为参考图
                    </small>
                  </span>
                  <ChevronRight size={16} />
                </button>
                <button
                  className="scene-choice"
                  disabled={!!busy}
                  onClick={() => void bridge("frames")}
                >
                  <Camera size={20} />
                  <span>
                    <strong>使用首尾帧生成</strong>
                    <small>用开场和结束画面控制构图</small>
                  </span>
                  <ChevronRight size={16} />
                </button>
                <button
                  className="scene-choice"
                  disabled={!!busy}
                  onClick={() => void bridge("video")}
                >
                  <Play size={20} />
                  <span>
                    <strong>使用运镜视频生成</strong>
                    <small>提供完整镜头作为动作参考</small>
                  </span>
                  <ChevronRight size={16} />
                </button>
                <p>
                  下一步会打开创意画板，由你选择图片或视频模型、描述画面风格并开始生成。
                </p>
                <details className="scene-details">
                  <summary>只保存预览素材</summary>
                  <div className="scene-preview-actions">
                    <Button
                      variant="outline"
                      disabled={!!busy}
                      loading={busy === "保存画面"}
                      onClick={() =>
                        void work("保存画面", async () => {
                          await assetFrame(time);
                          toast.success("画面已保存到素材库");
                        })
                      }
                    >
                      <Camera size={16} />
                      保存当前画面
                    </Button>
                    <Button
                      variant="outline"
                      disabled={!!busy}
                      loading={busy === "导出镜头预览"}
                      onClick={() =>
                        void work("导出镜头预览", async () => {
                          await exportVideo();
                          toast.success("镜头预览已保存到素材库");
                        })
                      }
                    >
                      <Download size={16} />
                      保存镜头预览视频
                    </Button>
                  </div>
                </details>
              </section>
            )}
          </div>
          {step !== "output" && (
            <div className="scene-side-next">
              <Button
                disabled={!!busy}
                onClick={() => {
                  setStep(step === "build" ? "camera" : "output");
                  setPreview(step === "camera");
                  setPlaying(false);
                }}
              >
                {step === "build" ? "下一步：设计镜头" : "下一步：生成素材"}
                <ChevronRight size={15} />
              </Button>
            </div>
          )}
        </aside>
        {agent && (
          <div
            className={
              agent === "docked" ? "scene-agent-dock" : "scene-agent-floating"
            }
          >
            <CanvasAgentChat
              dockedLayout="inline"
              workspaceId={initial.workspace_id}
              mode={agent}
              onModeChange={setAgent}
              onClose={() => setAgent(null)}
              rectKey="scene-studio-agent"
              contextLine={`当前 3D 场景 scene_id=${initial.id}，workspace_id=${initial.workspace_id}。先用 get_scene 读取最新场景，再用 edit_scene 修改对象、材质、灯光或镜头。单位米，旋转角度。不要执行任意代码。`}
              emptyHint="描述空间、物体或镜头，让助手协助搭建。"
              placeholder="例如：给展厅加一组台阶，然后设计推进镜头…"
            />
          </div>
        )}
      </div>
      <SceneHistory
        scene={initial}
        open={revisions}
        onClose={() => setRevisions(false)}
        onRestore={(value) => {
          change(value);
          setRevisions(false);
          setSelected(null);
        }}
      />
    </div>
  );
}
