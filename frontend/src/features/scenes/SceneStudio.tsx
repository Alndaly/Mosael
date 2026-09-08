import { RenameDialog } from "@/components/app/modals";
import { SceneList } from "./SceneList";
import { LoadingState } from "@/components/layout/LoadingState";
import { EmptyState } from "@/components/layout/EmptyState";
import { SceneBlender } from "./SceneBlender";
import { SceneBlenderPull } from "./SceneBlenderPull";
import { useCanvasInputMode } from "@/components/app/canvasInputMode";
import { readSceneSnap, writeSceneSnap } from "./sceneSnap";
import { readClayReference, writeClayReference } from "./clayReference";
import { lightingPrompt, presetById } from "./lighting";
import { CanvasInputModeSwitch } from "@/components/app/CanvasInputModeSwitch";
import { useSceneFullscreen } from "./useSceneFullscreen";
import { SceneHistory } from "./SceneHistory";
import { SceneCameraPanel } from "./SceneCameraPanel";
import { SceneDopeSheet } from "./SceneDopeSheet";
import { SceneInspector } from "./SceneInspector";
import { Pick, Tool } from "./SceneControls";
import { ScenePanel } from "./ScenePanel";
import { SearchableSelect } from "@/components/ui/searchable-select";
import React from "react";
import { SceneSubsection } from "./SceneSubsection";
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
  ChevronFirst,
  ChevronLast,
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
  MAX_KEYS,
  frameForObject,
  moveSceneKeys,
  sameKey,
  type SceneKey,
  neighbourKeyTime,
  removeKeyAt,
  upsertKey,
} from "./sceneTracks";
import {
  cameraOfShot,
  sampleCamera,
  sampleObject,
  duplicateObject,
  initialScene,
  makeObject,
  makeShot,
  objectLabels,
  removeObjects,
  uid,
} from "./sceneGraph";
import { SHOT_FPS } from "./encodeVideo";
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
/**
 * 「添加」里能放进场景的东西。**按用途分组**,顺序即呈现顺序(SearchableSelect 不重排)。
 *
 * `keywords` 让人按拼音/英文/别名也搜得到 —— 展示名是中文,而很多人手里是英文习惯。
 */
const ADD_OPTIONS: {
  value: string;
  label: string;
  description?: string;
  group: string;
  keywords: string[];
}[] = [
  { value: "camera", label: objectLabels.camera, group: "镜头", keywords: ["camera", "jiwei", "机位", "摄像机"],
    description: "多一台机位就多一个可切换的视角" },
  { value: "figure", label: objectLabels.figure, group: "参照与舞台", keywords: ["figure", "person", "renwu"],
    description: "1.7 米的人形,用来判断构图和比例" },
  { value: "table", label: objectLabels.table, group: "参照与舞台", keywords: ["table", "zhuozi", "desk"] },
  { value: "plane", label: objectLabels.plane, group: "参照与舞台", keywords: ["plane", "floor", "dimian", "地板"] },
  { value: "room", label: objectLabels.room, group: "参照与舞台", keywords: ["room", "fangjian", "wall", "墙"] },
  { value: "stairs", label: objectLabels.stairs, group: "参照与舞台", keywords: ["stairs", "louti", "step"] },
  { value: "box", label: objectLabels.box, group: "基本体", keywords: ["box", "cube", "lifangti"] },
  { value: "sphere", label: objectLabels.sphere, group: "基本体", keywords: ["sphere", "ball", "qiuti"] },
  { value: "cylinder", label: objectLabels.cylinder, group: "基本体", keywords: ["cylinder", "yuanzhu", "tube"] },
  { value: "group", label: objectLabels.group, group: "其它", keywords: ["group", "zu", "folder"] },
  { value: "light", label: objectLabels.light, group: "其它", keywords: ["light", "lamp", "dengguang", "点光源"] },
  { value: "__import__", label: "导入 GLB / glTF", group: "其它", keywords: ["import", "glb", "gltf", "daoru", "model"],
    description: "从文件导入已有模型" },
];

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
          {/* 入口放在列表页,因为「我手上已经有个 Blender 工程」是**开始**一个场景的方式,
              不是某个已有场景里的操作 —— 详情页那条互通要求先从这边发送过去。 */}
          <SceneBlenderPull
            workspaceId={workspace.id}
            disabled={creating}
            onCreated={async (sceneId) => {
              await qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
              location.hash = `#/scenes?scene=${sceneId}`;
            }}
          />
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
  const [renaming, setRenaming] = React.useState(false);
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
    // 吸附是「我习惯这么干活」,不是这一次的临时状态 —— 和画布输入模式同一类,记住它。
    // 每次打开场景都退回关闭,等于让常开的人每次先点一下。
    [snap, setSnap] = React.useState(readSceneSnap),
    //: 交给模型时是否附一张灰模参考图。见 clayReference —— 是"我习惯怎么交",不是场景数据。
    [clay, setClay] = React.useState(readClayReference),
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
    [recovery, setRecovery] = React.useState<typeof draft | null>(null),
    /**
     * 正在手改姿态的那个物体 —— **它此刻不跟着轨走**。
     *
     * 一个有走位的物体,每一帧的姿态都由轨采样出来覆盖掉。于是拖动它的操作杆就成了一件
     * 看不见的事:松手的那一瞬间它就被采样值抹回去,而用户以为自己什么也没做成。
     * 专业 3D 软件里这一步是成立的 —— 拖动改的是"当前这个样子",按 `I` 才把它记进这一刻,
     * 换一个时刻它就回到轨上。这个状态就是那段"还没记下来的样子"。
     */
    [posing, setPosing] = React.useState<string | null>(null);
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
  //: 换一个时刻、换一个物体,那段"还没记下来的样子"就作废 —— 回到轨上。
  React.useEffect(() => setPosing(null), [time, selected, shotId]);
  const shot =
      draft.content.shots.find((s) => s.id === shotId) ??
      draft.content.shots[0],
    object = draft.content.objects.find((o) => o.id === selected);
  /** 拍当前镜头的那台机位。**运镜长在它身上** —— 见 docs/design/scene-time-and-cameras.md。 */
  const rig = cameraOfShot(draft.content, shot);
  function rigPatch(patch: Partial<SceneObject>) {
    if (rig) objectPatch(rig.id, patch);
  }
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
  /**
   * 快捷键。**照 Blender 的手势**:这一页的用户多半已经在别处练过这套手指记忆,而重新发明
   * 一套只会让两边都不顺手。
   *
   *   I / ⌥I   在当前时刻记一档 / 移除这一档      G / R / S  移动 / 旋转 / 缩放
   *   空格      播放暂停                          ⇧D         复制一份
   *   ← →      逐帧                              X / ⌫      删除
   *   ↑ ↓      跳到上/下一个关键帧                F          聚焦选中
   *
   * 单键的那些一律要求"没有按任何修饰键" —— 否则 ⌘S(保存)会顺手把工具切成缩放,
   * 而用户完全不知道自己刚才改了什么。
   */
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        e.defaultPrevented ||
        target.closest("input,textarea,[contenteditable=true],[role=dialog]") ||
        busy
      )
        return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        e.shiftKey ? redo() : undo();
        return;
      }
      // ⌥I 是 I 的一对,所以它在"单键"这条线之前先判。macOS 上 ⌥ 会改写 e.key,认 code。
      if (e.altKey && !e.metaKey && !e.ctrlKey && e.code === "KeyI") {
        e.preventDefault();
        clearKeyframe();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // 逐帧 / 跳帧。**一"帧"和导出的一帧是同一个数**(SHOT_FPS),否则对齐没有意义。
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const step = ((e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 10 : 1)) / SHOT_FPS;
        setPlaying(false);
        setTime((now) => Math.min(shot.duration, Math.max(0, now + step)));
        return;
      }
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        const times = keyTarget?.track.map((f) => f.time) ?? [];
        const next = neighbourKeyTime(times, time, e.key === "ArrowDown" ? 1 : -1);
        if (next === null) return;
        e.preventDefault();
        setPlaying(false);
        setTime(next);
        return;
      }
      if (e.shiftKey) {
        // ⇧D 复制一份。别的带 Shift 的单键这一页没有,所以到此为止。
        if (e.code === "KeyD" && selected) {
          e.preventDefault();
          update(duplicateObject(current.current.content, selected));
        }
        return;
      }
      switch (e.code) {
        case "Space":
          // 焦点停在某颗按钮上时,空格是"按下这颗按钮" —— 那是浏览器的语义,抢走它会让
          // 用户点完一个按钮之后再按空格得到两件事。画布和别处才归播放。
          if (target.closest("button,[role=button],a,[role=slider],summary")) return;
          e.preventDefault();
          togglePlayback();
          return;
        case "KeyI":
          e.preventDefault();
          recordKeyframe();
          return;
        case "KeyG":
          setMode("translate");
          return;
        case "KeyR":
          setMode("rotate");
          return;
        case "KeyS":
          setMode("scale");
          return;
        case "KeyF":
          view.current?.focus();
          return;
        case "KeyX":
        case "Delete":
        case "Backspace":
          if (!selected) return;
          e.preventDefault();
          update(removeObjects(current.current.content, [selected]));
          setSelected(null);
          return;
      }
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
  async function assetFrame(t: number, options?: { clay?: boolean }) {
    const blob = await view.current!.frame(shot, t, options);
    const suffix = options?.clay ? "-灰模" : "";
    return importAsset({
      workspaceId: initial.workspace_id,
      file: new File([blob], `${draft.name}-${shot.name}-${t.toFixed(2)}${suffix}.png`, {
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
        if (clay) {
          const gray = await assetFrame(time, { clay: true });
          sources.push({ asset_id: gray.id, role: "reference_image" });
        }
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
          // **打光要一起说出去。** 参考帧只表达"光从哪来"(靠影子),而"这是什么光"——
          // 暖的冷的、硬的柔的、什么场合 —— 只有文字说得清。此前这句只提构图和运镜,
          // 光完全由模型自己发挥,于是同一场景的两个镜头打光对不上,剪到一起就穿帮。
          prompt: [
            kind === "image"
              ? `参考 3D 场景「${draft.name}」的画面构图、空间布局与摄像机视角，生成精细的图片。`
              : `参考 3D 场景「${draft.name}」的构图、空间布局和运镜，生成最终视频。`,
            `打光：${lightingPrompt(draft.content.lighting)}。`,
            clay ? "另一张灰模参考图只用于读取光影与体积，不要照搬它的灰色材质。" : "",
          ].filter(Boolean).join(""),
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
  /** 给拍这个镜头的机位在某一刻记一档 —— 用的是**画面里当前的视角**,不是相机存着的静止姿态。 */
  function recordView(at: number) {
    if (!rig) return;
    const time = Math.min(shot.duration, Math.max(0, at));
    const track = upsertKey(rig.track, { ...view.current!.camera(), time });
    if (!track) {
      toast.error(`单个镜头最多 ${MAX_KEYS} 个途经点，请先移除一个。`);
      return;
    }
    rigPatch({ track });
    setTime(time);
    toast.success(
      time === 0 ? "已设置镜头起点" : time === shot.duration ? "已设置镜头终点" : "已记录当前视角",
    );
  }
  const keyTarget = object;
  /** 普通打帧只记录物体姿态。采纳自由视角另有明确的「记录此视角」动作。 */
  function recordKeyframe(id = selected, at = time) {
    const target = current.current.content.objects.find(o => o.id === id);
    if (!target) return;
    const frame = frameForObject(target, shot, at, posing === target.id);
    const track = upsertKey(target.track, frame);
    if (!track) {
      toast.error(`一个物体最多 ${MAX_KEYS} 个关键帧，请先移除一个。`);
      return;
    }
    objectPatch(target.id, { track });
    setPosing(null);
    setPlaying(false);
  }
  function samplePose(target: SceneObject) {
    if (target.kind !== "camera") return sampleObject(target, shot, time);
    const frame = sampleCamera(target, shot, time);
    return {position: frame.position, target: frame.target, fov: frame.fov};
  }
  function deleteKeys(keys: SceneKey[]) {
    update({...current.current.content, objects: current.current.content.objects.map(o => ({
      ...o, track: o.track.filter(f => !keys.some(key => sameKey(key, {id: o.id, time: f.time}))),
    }))});
    setPosing(null);
    setPlaying(false);
  }
  function moveKeys(keys: SceneKey[], delta: number) {
    const content = current.current.content;
    const end = Math.max(shot.duration, ...content.objects.flatMap(o => o.track.map(f => f.time)));
    const next = moveSceneKeys(content, keys, delta, end);
    if (!next) { toast.error("目标时刻已有关键帧，或超出时间范围"); return false; }
    update(next); setPosing(null); setPlaying(false);
    return true;
  }
  /** `⌥I` —— 移除这一刻那一档。和 `I` 成对,所以不去挤 `X`(那个删的是物体)。 */
  function clearKeyframe() {
    if (!keyTarget) return;
    const track = removeKeyAt(keyTarget.track, time);
    if (!track) {
      toast.error("这一刻没有关键帧");
      return;
    }
    objectPatch(keyTarget.id, { track });
    toast.success(
      track.length ? `已移除 ${time.toFixed(1)} 秒那一档` : `「${keyTarget.name}」不再随时间移动`,
    );
  }
  return (
    <div
      ref={studioRoot}
      className="scene-studio"
      data-screen-mode={fullscreen.active ? "viewport" : undefined}
    >
      <RenameDialog open={renaming} title="重命名场景" initialValue={draft.name} onCancel={() => setRenaming(false)} onSubmit={(name) => { change({ ...current.current, name }); setRenaming(false); }} />
      <header className="scene-header">
        <Tool label="返回场景列表" onClick={onBack}>
          <ArrowLeft size={17} />
        </Tool>
        <div className="scene-heading">
          <button className="scene-name truncate text-left" title="重命名场景" aria-label="重命名场景" onClick={() => setRenaming(true)}>{draft.name}</button>
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
          <span className="scene-tool-divider" aria-hidden="true" />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAgent(agent ? null : "docked")}
          >
            <Sparkles size={15} />
            建模助手
          </Button>
          <SceneBlender scene={initial} pending={autosave.pending || !!error} busy={!!busy} work={work}
            //: 和「恢复历史版本」走同一条路(update → change):进撤销栈、由自动保存落库。
            //: 接收因此是一次可撤销的编辑,而不是一次绕过编辑器的写库。
            apply={(content) => { update(content); setSelected(null); setTime(0); setPlaying(false); }}
            prepare={async () => {
            const snapshot = JSON.stringify(current.current);
            if (snapshot !== saved.current) throw new Error("请等待场景保存完成后重试。");
            const sourceRevision = revision.current;
            const blob = await view.current!.glb();
            if (snapshot !== JSON.stringify(current.current) || revision.current !== sourceRevision)
              throw new Error("场景在导出时发生变化，请重新发送。");
            return { revision: sourceRevision, shotId, blob };
          }} />
          {/* **「生成素材」从一个步骤变成一个入口。**
              它不是"搭完场景之后的第三步" —— 它是随时可以做的一件事:摆好一个画面就能去生成,
              回来改改再生成一次。做成步骤反而把它锁在流程末尾,还占掉一整块侧栏。 */}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" disabled={!!busy}>
                <Sparkles size={15} />
                生成素材
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="scene-generate">
              <div className="scene-output-panel">
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
                {/* **灰模是第二张参考图,不是替代。** 3D 里的占位色看着塑料,会把模型往塑料感
                    带;而影子、明暗过渡、体积这些光的信息在灰模上反而更干净。生成侧的
                    reference_image 上限是 9,多送一张是现成能力。 */}
                <label className="scene-toggle">
                  <input
                    type="checkbox"
                    checked={clay}
                    onChange={() => setClay((on) => writeClayReference(!on))}
                  />
                  <span>
                    <strong>同时送一张灰模参考图</strong>
                    <small>统一材质、只留光影，帮模型读准打光</small>
                  </span>
                </label>
                <p>
                  当前打光「{presetById(draft.content.lighting.preset)?.label ?? "自定义"}」会一并写进提示词。
                  下一步会打开创意画板，由你选择图片或视频模型、描述画面风格并开始生成。
                </p>
                <SceneSubsection title="只保存预览素材">
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
                </SceneSubsection>
              </div>
            </PopoverContent>
          </Popover>
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
      <div
        className="scene-workspace"
        data-agent={agent === "docked"}
      >
        <main className="scene-stage">
          <div className="scene-stage-bar">
            {/* 三个步骤撤掉之后,这三个名字要能自己说清楚在看什么:
                「自由视角」是你自己在场景里飞,「机位视角」是从当前机位看出去(所见即成片),
                「俯瞰全场」是拉开看机位和走位的轨迹。此前叫「编辑/镜头画面/全局动线」,
                前两个像是两种编辑模式,而实际差别是**从谁的眼睛看**。 */}
            <div className="scene-segment" role="group" aria-label="从哪儿看">
              {(
                [
                  ["edit", "自由视角", "自己在场景里飞"],
                  ["camera", "机位视角", "从当前机位看出去,所见即成片"],
                  ["observe", "俯瞰全场", "拉开看机位和走位的轨迹"],
                ] as const
              ).map(([value, label, hint]) => (
                <button
                  key={value}
                  title={hint}
                  aria-pressed={viewMode === value}
                  onClick={() => setViewMode(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="scene-actions">
              {viewMode === "edit" && (
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
              {viewMode === "edit" && <span className="scene-tool-divider" aria-hidden="true" />}
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
                  <p>
                    编辑视角用于调整构图；镜头画面展示最终取景；全局动线可在播放时观察摄像机位置与朝向。
                  </p>
                  {/* **键位表就放在这里。** 快捷键不写出来等于没有 —— 而这一页照的是 Blender
                      的手势,用惯了的人会去试,没用过的人得有一处能看见。 */}
                  <strong>快捷键</strong>
                  <dl className="scene-keymap">
                    <dt>G / R / S</dt><dd>移动 / 旋转 / 缩放</dd>
                    <dt>I / ⌥I</dt><dd>在此刻记一档 / 移除这一档</dd>
                    <dt>空格</dt><dd>播放、暂停</dd>
                    <dt>← →</dt><dd>逐帧（按住 ⇧ 走十帧）</dd>
                    <dt>↑ ↓</dt><dd>跳到上 / 下一个关键帧</dd>
                    <dt>⇧D</dt><dd>复制一份</dd>
                    <dt>X</dt><dd>删除选中</dd>
                    <dt>F</dt><dd>聚焦选中</dd>
                    <dt>⌘Z / ⇧⌘Z</dt><dd>撤销 / 重做</dd>
                  </dl>
                </PopoverContent>
              </Popover>
            </div>
          </div>
          <SceneViewport
            ref={view}
            workspace={initial.workspace_id}
            sceneId={initial.id}
            content={draft.content}
            selected={selected}
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
            }}
            posing={posing}
            onTransform={(id, patch) => {
              // 记下"这个物体现在被手改过" —— 有走位的物体在下一帧会被采样值抹回去,
              // 而用户要的是把这个样子留到按下 `I` 为止。
              setPosing(id);
              objectPatch(id, patch);
            }}
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
          {/* **时间条常驻。** 运镜和走位在同一条时间轴上,而"物体在第几秒在哪儿"这件事
              没有时间条就无从表达 —— 它不该藏在某个步骤后面。 */}
          <section className="scene-timeline" aria-label="镜头播放控制">
              {/* **关键帧视图:按物体分行,位置即时间。** 此前这里只画当前机位的那一条轨 ——
                  而场景里的物体和运镜共用同一条时间轴,只画相机的话,"第 3 秒人走到门口、
                  同一刻镜头推进"这件事在界面上没有位置可以表达。时间滑块收进它的标尺行,
                  两者共用一条横轴才对得齐。 */}
              <SceneDopeSheet
                controls={<div className="scene-shot-row">
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
                    // 新建镜头 = 新建一台机位 + 一个用它的镜头。**它们成对出现** ——
                    // 镜头必须指向一台真实存在的相机。机位停在你当前看的那个视角上。
                    const here = view.current!.camera();
                    const { camera, shot: s } = makeShot(
                      `镜头 ${draft.content.shots.length + 1}`,
                    );
                    camera.position = here.position;
                    camera.target = here.target;
                    camera.fov = here.fov;
                    update({
                      ...draft.content,
                      objects: [...draft.content.objects, camera],
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
                <span className="scene-tool-divider" aria-hidden="true" />
                <Tool label="回到起点" onClick={() => { setTime(0); setPlaying(false); }}><ChevronFirst size={16} /></Tool>
                <Tool
                  label={playing ? "暂停" : "播放镜头"}
                  disabled={!!busy}
                  onClick={togglePlayback}
                >
                  {playing ? <Pause size={17} /> : <Play size={17} />}
                </Tool>
                <Tool label="跳到结尾" onClick={() => { setTime(shot.duration); setPlaying(false); }}><ChevronLast size={16} /></Tool>
                <span className="scene-time">
                  {time.toFixed(1)} / {shot.duration.toFixed(1)} s
                </span>
              </div>}
                content={draft.content}
                shot={shot}
                time={time}
                selectedId={selected}
                playing={playing}
                disabled={!!busy}
                onInsert={recordKeyframe}
                onDelete={deleteKeys}
                onMove={moveKeys}
                onSeek={(next) => {
                  setTime(next);
                  setPlaying(false);
                }}
                onSelect={(id) => {
                  setSelected(id);
                  // 选择轨道不改变观察方式；打帧与当前显示哪台相机是独立操作。
                }}
              />
            </section>
        </main>
        <aside className="scene-side">
          <div className="scene-side-scroll">
            <>
                <ScenePanel
                  id="objects"
                  title="场景中的物体"
                  count={draft.content.objects.length}
                  actions={
                    <>
                    {/* **导入只留这一个入口。** 此前「添加」弹层里有一条「导入 GLB / glTF」,
                        列表底下还有一颗整宽的「导入模型」—— 同一件事两个入口,而且长得完全
                        不一样,读者要先判断它们是不是同一件事。收成标题栏这一颗图标按钮。 */}
                    {/* 用 SearchableSelect 而不是手写弹层:物体种类只会越来越多,而手写那个
                        既不分组、又没有高度上限(十几项就把屏幕撑满)、也搜不了。这颗控件
                        本来就是给"选项多到普通 Select 会溢出屏幕"准备的。 */}
                    <SearchableSelect
                      value=""
                      onValueChange={(kind) => {
                        if (kind === "__import__") file.current?.click();
                        else add(kind as SceneObject["kind"]);
                      }}
                      searchPlaceholder="搜索物体类型"
                      emptyText="没有匹配的类型"
                      options={ADD_OPTIONS}
                      trigger={
                        <Button size="icon-sm" title="添加物体" aria-label="添加物体">
                          <Plus size={16} />
                        </Button>
                      }
                    />
                    <Button
                      variant="outline"
                      size="icon-sm"
                      title="导入 GLB / glTF 模型"
                      aria-label="导入 GLB / glTF 模型"
                      onClick={() => file.current?.click()}
                    >
                      <Upload size={16} />
                    </Button>
                    </>
                  }
                >
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
                </ScenePanel>

                <ScenePanel id="inspector" title={object ? "调整物体" : "场景外观"}>
                  <SceneInspector
                    content={draft.content}
                    object={object && posing !== object.id ? {...object, ...samplePose(object)} : object}
                    objectPatch={(id, patch) => {
                      if (patch.position || patch.rotation || patch.scale || patch.target || patch.fov !== undefined) setPosing(id);
                      const target = current.current.content.objects.find(o => o.id === id);
                      const transform = patch.position || patch.rotation || patch.scale || patch.target || patch.fov !== undefined;
                      objectPatch(id, target && transform && posing !== id
                        ? {...samplePose(target), ...patch}
                        : patch);
                    }}
                    update={update}
                    setSelected={setSelected}
                  />
                </ScenePanel>
            </>
            {/* **镜头设置跟着「选中了哪台机位」走。** 相机现在是场景里的物体,它的运镜、
                时长、比例本来就该在选中它时出现 —— 而不是藏在一个叫「设计镜头」的步骤后面。 */}
            {object?.kind === "camera" && rig && object.id === rig.id && (
              <ScenePanel id="camera" title="让镜头怎么走">
              <SceneCameraPanel
                shot={shot}
                rig={rig!}
                time={time}
                preview={viewMode !== "edit"}
                onPatch={shotPatch}
                onRig={rigPatch}
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
              </ScenePanel>
            )}
          </div>
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
