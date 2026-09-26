import { RenameDialog } from "@/components/app/modals";
import { PageHeading, STUDIO_PAGE } from "@/components/layout/StudioPage";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { cn } from "@/lib/utils";
import { listenKeys } from "@/lib/shortcuts";
import { HANDLE_COLUMN, handleOffset, useResizableSidebar } from "@/lib/useResizableSidebar";
import { SceneList } from "./SceneList";
import { LoadingState } from "@/components/layout/LoadingState";
import { EmptyState } from "@/components/layout/EmptyState";
import { SceneBlender } from "./SceneBlender";
import { SceneBlenderPull } from "./SceneBlenderPull";
import { useCanvasInputMode } from "@/components/app/canvasInputMode";
import { readSceneSnap, writeSceneSnap } from "./sceneSnap";
import { readClayReference, writeClayReference } from "./clayReference";
import { forgetSceneView, readSceneView, rememberedShot, writeSceneView } from "./sceneViewMemory";
import { blockoutPrompt } from "./blockoutPrompt";
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
  ArchiveRestore,
  ArrowLeft,
  Box,
  Boxes,
  Camera,
  Check,
  CheckSquare,
  ChevronFirst,
  ChevronLast,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  CircleAlert,
  Download,
  Eye,
  EyeOff,
  Focus,
  Folder,
  HelpCircle,
  History,
  Image as ImageIcon,
  Lightbulb,
  Loader2,
  Magnet,
  Maximize,
  Minimize,
  Minus,
  Move,
  Pause,
  Play,
  Plus,
  RotateCcw,
  RotateCw,
  Scaling,
  Sparkles,
  Trash2,
  Video,
} from "lucide-react";
import { toast } from "sonner";
import type { Workspace } from "@/api/client";
import { importAsset } from "@/api/domains/assets";
import { createBoard, updateBoard, withSlotProducer, type BoardItem } from "@/api/domains/boards";
import { errorText } from "@/api/errorMessage";
import {
  createScene,
  deleteScene,
  getScene,
  listSceneModels,
  listScenes,
  saveScene,
  uploadSceneModel,
  type Scene,
  type SceneContent,
  type SceneObject,
  type SceneShot,
} from "@/api/domains/scenes";
import { Button } from "@/components/ui/button";
import { KbdGroup } from "@/components/ui/kbd";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  CanvasAgentChat,
  type CanvasAgentMode,
} from "@/features/agent/CanvasAgentChat";
import { useAutosave } from "@/lib/useAutosave";
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
  hiddenObjectIds,
  initialScene,
  makeObject,
  makeShot,
  objectLabels,
  objectTree,
  removeObjects,
  removeShot,
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
  label: MessageKey;
  description?: MessageKey;
  group: MessageKey;
  keywords: string[];
}[] = [
  { value: "camera", label: objectLabels.camera, group: "sceneAddGroupCamera", keywords: ["camera", "jiwei", "机位", "摄像机"],
    description: "sceneAddCameraHint" },
  { value: "figure", label: objectLabels.figure, group: "sceneAddGroupStage", keywords: ["figure", "person", "renwu"],
    description: "sceneAddFigureHint" },
  { value: "table", label: objectLabels.table, group: "sceneAddGroupStage", keywords: ["table", "zhuozi", "desk"] },
  { value: "plane", label: objectLabels.plane, group: "sceneAddGroupStage", keywords: ["plane", "floor", "dimian", "地板"] },
  { value: "room", label: objectLabels.room, group: "sceneAddGroupStage", keywords: ["room", "fangjian", "wall", "墙"] },
  { value: "stairs", label: objectLabels.stairs, group: "sceneAddGroupStage", keywords: ["stairs", "louti", "step"] },
  { value: "box", label: objectLabels.box, group: "sceneAddGroupPrimitives", keywords: ["box", "cube", "lifangti"] },
  { value: "sphere", label: objectLabels.sphere, group: "sceneAddGroupPrimitives", keywords: ["sphere", "ball", "qiuti"] },
  { value: "cylinder", label: objectLabels.cylinder, group: "sceneAddGroupPrimitives", keywords: ["cylinder", "yuanzhu", "tube"] },
  { value: "group", label: objectLabels.group, group: "sceneAddGroupOther", keywords: ["group", "zu", "folder"] },
  { value: "light", label: objectLabels.light, group: "sceneAddGroupOther", keywords: ["light", "lamp", "dengguang", "点光源"] },
  { value: "__import__", label: "sceneAddImport", group: "sceneAddGroupOther", keywords: ["import", "glb", "gltf", "daoru", "model"],
    description: "sceneAddImportHint" },
];

/** 一个模型在「添加」菜单里占的那一项。前缀把它和内置形状分开 —— 模型的 id 是十六进制串,
 *  和 kind 撞不上,但靠"撞不上"来区分是等着出事。 */
const MODEL_PREFIX = "model:";

/** 列表里那个小图标。**组、相机、灯要分得出来** —— 全是同一个方块的话,树的结构没人看得懂。 */
function ObjectKindIcon({ kind }: { kind: SceneObject["kind"] }) {
  if (kind === "group") return <Folder size={14} />;
  if (kind === "camera") return <Video size={14} />;
  if (kind === "light") return <Lightbulb size={14} />;
  if (kind === "model") return <Boxes size={14} />;
  return <Box size={14} />;
}

const readId = () =>
  new URLSearchParams(location.hash.split("?")[1] ?? "").get("scene");
export function SceneStudio({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
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
        demo ? t("sceneDemoName") : t("sceneUntitled"),
        initialScene(t, demo),
      );
      qc.setQueryData(["scene", workspace.id, s.id], s);
      await qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
      location.hash = `#/scenes?scene=${s.id}`;
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setCreating(false);
    }
  }
  if (id) {
    if (scene.isPending)
      return (
        <LoadingState label={t("sceneOpening")} />
      );
    if (scene.error)
      return (
        <div className="flex h-full min-h-0 flex-col overflow-auto">
          <EmptyState icon={<Box />} title={t("sceneOpenFailed")} body={scene.error.message} action={<Button
            onClick={() => {
              location.hash = "#/scenes";
            }}
          >
            {t("sceneBackToList")}
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
    <div className={cn("scene-library", STUDIO_PAGE)}>
      {/* 页头用**和画板/工作流同一个** PageHeading:此前这里是一套手写的 header,于是三个
          同级列表页的标题字号、按钮对齐(居中 vs 与描述行齐平)、页面内距各不相同,并排一看就
          知道不是一家的。计数徽章也是它带来的 —— 另外两页都有,只有这页没有。 */}
      <PageHeading
        title={t("navScenes")}
        description={t("studioScenesDesc")}
        count={list.data?.length}
        actions={
          <>
            {!!list.data?.length && <Button variant="outline" aria-pressed={selecting} onClick={() => setSelecting(!selecting)}><CheckSquare size={16} />{selecting ? t("scenesSelectDone") : t("bulkSelect")}</Button>}
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
              {t("scenesOpenSample")}
            </Button>
            <Button disabled={creating} onClick={() => void create(false)}>
              <Plus size={16} />
              {t("scenesNew")}
            </Button>
          </>
        }
      />
      {list.isPending ? (
        <LoadingState className="h-auto flex-1" label={t("scenesLoading")} />
      ) : list.error ? (
        <div className="flex min-h-0 flex-1 flex-col" role="alert">
          <EmptyState icon={<Box />} title={t("sceneLoadFailed")} body={list.error.message} action={<Button variant="secondary" onClick={() => void list.refetch()}>{t("retry")}</Button>} />
        </div>
      ) : !list.data?.length ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <EmptyState icon={<Box />} title={t("sceneEmptyTitle")} body={t("sceneEmptyBody")} action={<Button disabled={creating} onClick={() => void create(true)}>{t("sceneTrySample")}</Button>} />
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
              toast.success(t("sceneRenamed"));
              return true;
            } catch (e) { toast.error(errorText(e)); return false; }
          }}
          onDelete={async scenes => {
            const results = await Promise.allSettled(scenes.map(scene => deleteScene(workspace.id, scene.id)));
            const done = scenes.filter((_, i) => results[i].status === "fulfilled").map(scene => scene.id);
            for (const sceneId of done) {
              qc.removeQueries({ queryKey: ["scene", workspace.id, sceneId] });
              localStorage.removeItem(`mosael.scene-draft:${workspace.id}:${sceneId}`);
              forgetSceneView(workspace.id, sceneId);
            }
            await qc.invalidateQueries({ queryKey: ["scenes", workspace.id] });
            if (done.length) toast.success(t("sceneDeletedCount").replace("{n}", String(done.length)));
            const failure = results.find(r => r.status === "rejected");
            if (failure?.status === "rejected") toast.error(t("sceneDeletePartialFailed").replace("{reason}", String(failure.reason)));
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
  const t = useI18n();
  const [navigation] = useCanvasInputMode();
  const [renaming, setRenaming] = React.useState(false);
  /** 收起来的那些组。**不持久化** —— 它是"我这会儿在看哪一块",不是设置。 */
  const [collapsed, setCollapsed] = React.useState<ReadonlySet<string>>(() => new Set());
  /** 这个工作区里已经有的模型。**它们归工作区,不归场景** —— 所以在「添加」里和几何体
   *  并排列出来,一件道具导一次、哪个场景都摆得上,不必每个场景重新传一遍。 */
  const sceneModels = useQuery({
    queryKey: ["scene-models", initial.workspace_id],
    queryFn: () => listSceneModels(initial.workspace_id),
  });
  const addOptions = React.useMemo(
    () => [
      ...ADD_OPTIONS.map((option) => ({
        ...option,
        label: t(option.label),
        group: t(option.group),
        description: option.description && t(option.description),
      })),
      ...(sceneModels.data ?? []).map((m) => ({
        value: MODEL_PREFIX + m.id,
        label: m.name,
        group: t("sceneAddGroupModels"),
        keywords: ["model", "glb", "moxing", m.name],
        description: `${(m.size / 1024 / 1024).toFixed(1)} MB · ${m.format.toUpperCase()}`,
      })),
    ],
    [sceneModels.data, t],
  );
  const studioRoot = React.useRef<HTMLDivElement>(null);
  const fullscreen = useSceneFullscreen(studioRoot);
  const qc = useQueryClient(),
    [draft, setDraft] = React.useState(() => ({
      name: initial.name,
      content: initial.content,
    })),
    current = React.useRef(draft);
  current.current = draft;
  /** 有孩子的那些物体(组,以及任何被当成父级用的东西)—— 一键收拢要作用在它们身上。 */
  const groupIds = React.useMemo(
    () => objectTree(draft.content).filter((row) => row.children > 0).map((row) => row.object.id),
    [draft.content],
  );
  const allCollapsed = groupIds.length > 0 && groupIds.every((id) => collapsed.has(id));
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
    //: 视角档和镜头按场景记住 —— 个人的编辑器状态,存本地,不进场景(见 sceneViewMemory)。
    [shotId, setShotId] = React.useState(() =>
      rememberedShot(readSceneView(initial.workspace_id, initial.id), initial.content.shots),
    ),
    [time, setTime] = React.useState(0),
    [viewMode, setViewMode] = React.useState(() => readSceneView(initial.workspace_id, initial.id).mode),
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
  //: 两栏可拖宽,和剪辑页同一套。智能体栏的上下限和工作流、画板、剪辑页的智能体栏一致。
  const sidePanel = useResizableSidebar("scene-side", { min: 240, max: 480, fallback: 304 });
  const agentPanel = useResizableSidebar("scene-agent", { min: 320, max: 640, fallback: 400 });
  const agentDocked = agent === "docked";
  React.useEffect(
    () => writeSceneView(initial.workspace_id, initial.id, { mode: viewMode, shotId }),
    [initial.workspace_id, initial.id, viewMode, shotId],
  );
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
      if (mounted.current) setError(errorText(e));
      throw e;
    }
  });
  function change(next: typeof draft) {
    const previous = current.current;
    setHistory((h) => [...h.slice(-49), previous]);
    setFuture([]);
    current.current = next;
    setDraft(next);
    try {
      localStorage.setItem(cacheKey, JSON.stringify(next));
    } catch {
      toast.error(t("sceneDraftStorageFull"));
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
  function removeSceneObjects(ids: string[]) {
    const before = current.current.content;
    const content = removeObjects(before, ids);
    if (content === before) {
      toast.error(t("sceneCantDeleteLastShotCamera"));
      return;
    }
    update(content);
    // 镜头是跟着机位一起走的 —— 说出来,不然镜头下拉里少了一项却没人知道为什么。
    const gone = before.shots.filter((s) => !content.shots.includes(s));
    if (gone.length) toast.info(t("sceneShotsRemovedWithCamera").replace("{names}", gone.map((s) => s.name).join(t("listSeparator"))));
    if (!content.objects.some(object => object.id === selected)) setSelected(null);
  }
  /** 藏 / 显示一个物体。**只改它自己那一位**:藏一个组时孩子们各自的标记原样留着,
   *  再显示这个组,原先就藏着的孩子仍然藏着(和 Blender 一样)。走 objectPatch → update,
   *  所以能撤销,也跟着自动保存进场景。 */
  function toggleHidden(id: string) {
    const target = current.current.content.objects.find((o) => o.id === id);
    if (target) objectPatch(id, { hidden: !target.hidden });
  }
  /** ⌥H:全部显示。一步 update,撤销时一次全回来。 */
  function revealAll() {
    const content = current.current.content;
    if (!content.objects.some((o) => o.hidden)) return;
    update({ ...content, objects: content.objects.map((o) => (o.hidden ? { ...o, hidden: false } : o)) });
  }
  function undo() {
    if (!history.length) return;
    const next = history[history.length - 1];
    const previous = current.current;
    setFuture((f) => [previous, ...f]);
    setHistory((h) => h.slice(0, -1));
    current.current = next;
    setDraft(next);
    localStorage.setItem(cacheKey, JSON.stringify(next));
  }
  function redo() {
    if (!future.length) return;
    const next = future[0];
    const previous = current.current;
    setHistory((h) => [...h, previous]);
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
  /** 实际看不见的物体(自己藏了或在藏起来的组里)。列表按它淡显。 */
  const hiddenIds = hiddenObjectIds(draft.content.objects);
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
   *   H / ⌥H   藏 / 显示选中,全部显示
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
      // ⌥H 同理:它是 H 的一对。Blender 里 H 只藏不显,但这里藏起来的物体仍可以从列表里
      // 选中,所以 H 做成开关 —— 选中一个藏着的再按一次就回来了。
      if (e.altKey && !e.metaKey && !e.ctrlKey && e.code === "KeyH") {
        e.preventDefault();
        revealAll();
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
          update(duplicateObject(current.current.content, selected, t));
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
        case "KeyH":
          if (!selected) return;
          e.preventDefault();
          toggleHidden(selected);
          return;
        case "KeyX":
        case "Delete":
        case "Backspace":
          if (!selected) return;
          e.preventDefault();
          removeSceneObjects([selected]);
          return;
      }
    };
    return listenKeys(window, key);
  });
  function add(kind: SceneObject["kind"]) {
    if (draft.content.objects.length >= 500) {
      toast.error(t("sceneObjectLimit").replace("{n}", "500"));
      return;
    }
    const o = makeObject(kind, { name: t(objectLabels[kind]) });
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
      toast.error(errorText(e));
    } finally {
      if (mounted.current) {
        setBusy("");
        setProgress(0);
      }
    }
  }
  /** 把模型库里的一份摆进场景。模型归工作区,所以这一步不需要上传 —— 它已经在了。 */
  function placeModel(name: string, modelId: string) {
    const o = makeObject("model", { name, model_id: modelId });
    update({
      ...current.current.content,
      objects: [...current.current.content.objects, o],
    });
    setSelected(o.id);
  }
  async function importModel(f: File) {
    await work(t("sceneBusyImportModel"), async () => {
      const m = await uploadSceneModel(initial.workspace_id, f);
      // 传完就进了工作区的模型库,别的场景也摆得上了 —— 让那份列表立刻看得到。
      void qc.invalidateQueries({ queryKey: ["scene-models", initial.workspace_id] });
      placeModel(m.name, m.id);
    });
  }
  async function assetFrame(at: number, options?: { clay?: boolean }) {
    const blob = await view.current!.frame(shot, at, options);
    const suffix = options?.clay ? `-${t("sceneClaySuffix")}` : "";
    return importAsset({
      workspaceId: initial.workspace_id,
      file: new File([blob], `${draft.name}-${shot.name}-${at.toFixed(2)}${suffix}.png`, {
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
    await work(t("sceneBusyPrepareGenerate"), async () => {
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
        for (const [i, at] of [0, shot.duration].entries()) {
          const a = await assetFrame(at);
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
          //: 另外两件事同样要说:参考只是白模占位(不说的话成片会照着灰模画),以及画面里有什么
          //: (白模里的形状各是什么)。见 blockoutPrompt。
          prompt: blockoutPrompt({
            kind: kind === "image" ? "image" : "video",
            sceneName: draft.name,
            objects: draft.content.objects,
            lighting: lightingPrompt(draft.content.lighting, t),
            clay: kind === "image" && clay,
            t,
          }),
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
        //: 每一格过新建格子的那一处(api/domains/boards 的 withSlotProducer):生成那一格带着草稿(提示词、参考、
        //: 参数),产出者由它补上 —— 和画布上放下的一格同一个样子。此前漏写,选中了什么面板都不挂。
        canvas: { items: items.map((item) => withSlotProducer(item)), edges },
      });
      await qc.invalidateQueries({
        queryKey: ["boards", initial.workspace_id],
      });
      location.hash = `#/boards?board=${board.id}`;
      toast.success(kind === "image" ? t("sceneBridgeImageDone") : t("sceneBridgeVideoDone"));
    });
  }
  function applyCameraPose(patch: Partial<Pick<SceneObject, "position" | "target" | "fov">>) {
    if (!rig) return;
    const pose = posing === rig.id ? rig : sampleCamera(rig, shot, time);
    // Viewport samples may also carry time; only pose fields belong on an object.
    objectPatch(rig.id, {
      position: patch.position ?? pose.position,
      target: patch.target ?? pose.target,
      fov: patch.fov ?? pose.fov,
    });
    setPosing(rig.id);
    setPlaying(false);
  }
  const keyTarget = object;
  /** Every insertion records the selected object pose, including camera poses. */
  function recordKeyframe(id = selected, at = time) {
    const target = current.current.content.objects.find(o => o.id === id);
    if (!target) return;
    const frame = frameForObject(target, shot, at, posing === target.id);
    const track = upsertKey(target.track, frame);
    if (!track) {
      toast.error(t("sceneKeyLimit").replace("{n}", String(MAX_KEYS)));
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
    if (!next) { toast.error(t("sceneKeyMoveBlocked")); return false; }
    update(next); setPosing(null); setPlaying(false);
    return true;
  }
  /** `⌥I` —— 移除这一刻那一档。和 `I` 成对,所以不去挤 `X`(那个删的是物体)。 */
  function clearKeyframe() {
    if (!keyTarget) return;
    const track = removeKeyAt(keyTarget.track, time);
    if (!track) {
      toast.error(t("sceneNoKeyHere"));
      return;
    }
    objectPatch(keyTarget.id, { track });
    toast.success(
      track.length
        ? t("sceneKeyRemoved").replace("{time}", time.toFixed(1))
        : t("sceneObjectNoLongerAnimated").replace("{name}", keyTarget.name),
    );
  }
  return (
    <div
      ref={studioRoot}
      className="scene-studio"
      data-screen-mode={fullscreen.active ? "editor" : undefined}
    >
      <RenameDialog open={renaming} title={t("sceneRenameTitle")} initialValue={draft.name} onCancel={() => setRenaming(false)} pending={false} onSubmit={(name) => { change({ ...current.current, name }); setRenaming(false); }} />
      <header className="scene-header">
        <Tool label={t("sceneBackToList")} onClick={onBack}>
          <ArrowLeft size={17} />
        </Tool>
        <div className="scene-heading">
          <button className="scene-name truncate text-left" title={t("sceneRenameTitle")} aria-label={t("sceneRenameTitle")} onClick={() => setRenaming(true)}>{draft.name}</button>
          <span className="scene-save" role="status">
            {error ? (
              t("sceneUnsaved")
            ) : autosave.pending ? (
              t("sceneSaving")
            ) : (
              <>
                <Check size={13} />
                {t("sceneSaved")}
              </>
            )}
          </span>
        </div>
        <div className="scene-actions">
          <Tool
            label={t("undo")}
            onClick={undo}
            disabled={!history.length || !!busy}
          >
            <RotateCcw size={16} />
          </Tool>
          <Tool label={t("redo")} onClick={redo} disabled={!future.length || !!busy}>
            <RotateCw size={16} />
          </Tool>
          <Tool label={t("sceneHistory")} onClick={() => setRevisions(true)}>
            <History size={16} />
          </Tool>
          <span className="scene-tool-divider" aria-hidden="true" />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAgent(agent ? null : "docked")}
          >
            <Sparkles size={15} />
            {t("sceneAssistant")}
          </Button>
          <SceneBlender scene={initial} pending={autosave.pending || !!error} busy={!!busy} work={work}
            //: 和「恢复历史版本」走同一条路(update → change):进撤销栈、由自动保存落库。
            //: 接收因此是一次可撤销的编辑,而不是一次绕过编辑器的写库。
            apply={(content) => { update(content); setSelected(null); setTime(0); setPlaying(false); }}
            //: 只交出「发哪一版」—— GLB 由后端按这个修订生成(domain/scene_render/gltf),
            //: 所以草稿必须先落库:发的是库里那一份,不是屏幕上这一份。
            prepare={async () => {
            if (JSON.stringify(current.current) !== saved.current) throw new Error(t("sceneWaitForSave"));
            return { revision: revision.current, shotId };
          }} />
          {/* **「生成素材」从一个步骤变成一个入口。**
              它不是"搭完场景之后的第三步" —— 它是随时可以做的一件事:摆好一个画面就能去生成,
              回来改改再生成一次。做成步骤反而把它锁在流程末尾,还占掉一整块侧栏。 */}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" disabled={!!busy}>
                <Sparkles size={15} />
                {t("sceneGenerate")}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="scene-generate">
              <div className="scene-output-panel">
                <h2>{t("sceneGenerateTitle")}</h2>
                <p>{t("sceneGenerateBody")}</p>
                <div className="scene-output-summary">
                  <span>{shot.name}</span>
                  <small>
                    {t("sceneSeconds").replace("{n}", String(shot.duration))} · {shot.aspect}
                  </small>
                </div>
                <button
                  className="scene-choice"
                  disabled={!!busy}
                  onClick={() => void bridge("image")}
                >
                  <ImageIcon size={20} />
                  <span>
                    <strong>{t("sceneGenerateFromFrame")}</strong>
                    <small>
                      {t("sceneGenerateFromFrameHint").replace("{time}", time.toFixed(1))}
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
                    <strong>{t("sceneGenerateFromFrames")}</strong>
                    <small>{t("sceneGenerateFromFramesHint")}</small>
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
                    <strong>{t("sceneGenerateFromVideo")}</strong>
                    <small>{t("sceneGenerateFromVideoHint")}</small>
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
                    <strong>{t("sceneClayToggle")}</strong>
                    <small>{t("sceneClayToggleHint")}</small>
                  </span>
                </label>
                <p>
                  {t("sceneGenerateLightingNote").replace("{lighting}", t(presetById(draft.content.lighting.preset)?.label ?? "sceneLightingCustom"))}{" "}
                  {t("sceneGenerateNextStep")}
                </p>
                <SceneSubsection title={t("sceneSavePreviewOnly")}>
                  <div className="scene-preview-actions">
                    <Button
                      variant="outline"
                      disabled={!!busy}
                      loading={busy === t("sceneBusySaveFrame")}
                      onClick={() =>
                        void work(t("sceneBusySaveFrame"), async () => {
                          await assetFrame(time);
                          toast.success(t("sceneFrameSaved"));
                        })
                      }
                    >
                      <Camera size={16} />
                      {t("sceneSaveFrame")}
                    </Button>
                    <Button
                      variant="outline"
                      disabled={!!busy}
                      loading={busy === t("sceneBusyExportPreview")}
                      onClick={() =>
                        void work(t("sceneBusyExportPreview"), async () => {
                          await exportVideo();
                          toast.success(t("scenePreviewSaved"));
                        })
                      }
                    >
                      <Download size={16} />
                      {t("sceneSavePreviewVideo")}
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
                {t("sceneExportFiles")}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="scene-export">
              <button
                onClick={() =>
                  void work(t("sceneBusyExportModel"), async () =>
                    download(await view.current!.glb(), `${draft.name}.glb`),
                  )
                }
              >
                {t("sceneExportGlb")}
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
                {t("sceneExportJson")}
              </button>
              <button
                onClick={() =>
                  void work(t("sceneBusySaveShotFrame"), async () => {
                    await assetFrame(time);
                    toast.success(t("sceneFrameSaved"));
                  })
                }
              >
                {t("sceneExportFrameToLibrary")}
              </button>
              <button
                onClick={() =>
                  void work(t("sceneBusyExportPreview"), async () => {
                    await exportVideo();
                    toast.success(t("scenePreviewSaved"));
                  })
                }
              >
                {t("sceneExportPreviewToLibrary")}
              </button>
              <hr />
              <button onClick={() => void bridge("image")}>
                {t("sceneExportToImage")}
              </button>
              <button onClick={() => void bridge("frames")}>
                {t("sceneExportFramesToVideo")}
              </button>
              <button onClick={() => void bridge("video")}>
                {t("sceneExportVideoToVideo")}
              </button>
              <p>{t("sceneExportNote")}</p>
            </PopoverContent>
          </Popover>
        </div>
      </header>
      {/* 两条提示带同一副骨架:图标 + 一句话 + 靠右的 xs 文字按钮。此前按钮是 sm(14px 字、
          32px 高)跟在 12px 的句子后面,读起来像句子里突然放大的两个词,而不是两个动作。 */}
      {error && (
        <div className="scene-notice" data-tone="error" role="alert">
          <CircleAlert size={14} aria-hidden="true" />
          <span>{t("sceneSaveFailed").replace("{error}", error)}</span>
          <span className="scene-notice-actions">
            <Button size="xs" variant="ghost" onClick={() => setDraft({ ...current.current })}>
              {t("retry")}
            </Button>
            <Button
              size="xs"
              variant="ghost"
              onClick={() =>
                download(
                  new Blob([JSON.stringify(draft, null, 2)], {
                    type: "application/json",
                  }),
                  `${draft.name}-${t("sceneDraftFileSuffix")}.json`,
                )
              }
            >
              {t("sceneExportDraft")}
            </Button>
          </span>
        </div>
      )}
      {recovery && (
        <div className="scene-notice" role="status">
          <ArchiveRestore size={14} aria-hidden="true" />
          <span>{t("sceneDraftFound")}</span>
          <span className="scene-notice-actions">
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                change(recovery);
                setRecovery(null);
              }}
            >
              {t("sceneRestoreDraft")}
            </Button>
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                setRecovery(null);
                localStorage.removeItem(cacheKey);
              }}
            >
              {t("sceneUseSaved")}
            </Button>
          </span>
        </div>
      )}
      <div
        className="scene-workspace"
        data-agent={agentDocked}
        style={{
          "--scene-side-width": `${sidePanel.width}px`,
          "--scene-agent-width": `${agentPanel.width}px`,
        } as React.CSSProperties}
      >
        {/* 分割线式排法(栏间 0 缝),拖柄压在线的正中 —— 和剪辑页一样,见 handleOffset。 */}
        <div
          className={cn("scene-resize-side", HANDLE_COLUMN)}
          style={{ right: handleOffset(sidePanel.width, { padding: agentDocked ? agentPanel.width : 0 }) }}
          role="separator"
          aria-orientation="vertical"
          onPointerDown={sidePanel.startDragFromRight}
        />
        {agentDocked && (
          <div
            className={cn("scene-resize-agent", HANDLE_COLUMN)}
            style={{ right: handleOffset(agentPanel.width) }}
            role="separator"
            aria-orientation="vertical"
            onPointerDown={agentPanel.startDragFromRight}
          />
        )}
        <main className="scene-stage">
          <div className="scene-stage-bar">
            {/* 三个步骤撤掉之后,这三个名字要能自己说清楚在看什么:
                「自由视角」是你自己在场景里飞,「机位视角」是从当前机位看出去(所见即成片),
                「俯瞰全场」是拉开看机位和走位的轨迹。此前叫「编辑/镜头画面/全局动线」,
                前两个像是两种编辑模式,而实际差别是**从谁的眼睛看**。 */}
            <div className="scene-segment" role="group" aria-label={t("sceneViewFrom")}>
              {(
                [
                  ["edit", "sceneViewFree", "sceneViewFreeHint"],
                  ["camera", "sceneViewCamera", "sceneViewCameraHint"],
                  ["observe", "sceneViewOverview", "sceneViewOverviewHint"],
                ] as const
              ).map(([value, label, hint]) => (
                <button
                  key={value}
                  title={t(hint)}
                  aria-pressed={viewMode === value}
                  onClick={() => setViewMode(value)}
                >
                  {t(label)}
                </button>
              ))}
            </div>
            <div className="scene-actions">
              {viewMode === "edit" && (
                <>
                  {(
                    [
                      ["translate", "sceneToolMove", Move],
                      ["rotate", "sceneToolRotate", RotateCw],
                      ["scale", "sceneToolScale", Scaling],
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
                      {t(label)}
                    </button>
                  ))}
                  {/* 吸附跟着这三个工具走:它改的正是它们的步长(位移 0.25 米、旋转 15°、
                      缩放 0.1,见 SceneViewport 的 setTranslationSnap 一带)。所以它和它们
                      同一排、同一种控件、同一个显示条件 —— 单拎到别处会读成一个无关的开关。
                      **不跟着 disabled**:没选中物体时它照样可以先打开,下一次拖动就生效。 */}
                  <button
                    className="scene-labeled-tool"
                    aria-pressed={snap}
                    title={t("sceneSnapHint")}
                    onClick={() => setSnap((on) => writeSceneSnap(!on))}
                  >
                    <Magnet size={15} />
                    {t("sceneSnap")}
                  </button>
                </>
              )}
              {viewMode === "edit" && <span className="scene-tool-divider" aria-hidden="true" />}
              {!preview && (
                <Popover>
                  <PopoverTrigger asChild>
                    <button className="scene-labeled-tool">
                      <Focus size={15} />
                      {t("sceneViewAngle")}
                    </button>
                  </PopoverTrigger>
                  <PopoverContent className="scene-add" align="end">
                    {(
                      [
                        ["perspective", "sceneViewPerspective"],
                        ["front", "sceneViewFront"],
                        ["top", "sceneViewTop"],
                      ] as const
                    ).map(([key, label]) => (
                      <button key={key} onClick={() => view.current?.view(key)}>
                        {t(label)}
                      </button>
                    ))}
                    <button onClick={() => view.current?.focus()}>
                      {observing ? t("sceneFrameAllPaths") : t("sceneFocusSelected")}
                    </button>
                  </PopoverContent>
                </Popover>
              )}
              <CanvasInputModeSwitch />
              <button
                className="scene-labeled-tool"
                /* 它全屏的是**这个视口**,不是整个编辑器 —— 按钮本来就长在视口自己那条
                   工具栏上,而人按它是想把画面看大。 */
                aria-label={fullscreen.active ? t("sceneExitFullscreen") : t("sceneFullscreenLabel")}
                title={fullscreen.active ? t("sceneExitFullscreenTitle") : t("sceneFullscreenTitle")}
                aria-pressed={fullscreen.active}
                onClick={() => void fullscreen.toggle()}
              >
                {fullscreen.active ? (
                  <Minimize size={15} />
                ) : (
                  <Maximize size={15} />
                )}
                {fullscreen.active ? t("sceneExitFullscreen") : t("sceneFullscreen")}
              </button>
              <Popover>
                <PopoverTrigger asChild>
                  <button className="scene-tool" aria-label={t("sceneHelp")}>
                    <HelpCircle size={16} />
                  </button>
                </PopoverTrigger>
                <PopoverContent className="scene-help" align="end">
                  <strong>{t("sceneHelpTitle")}</strong>
                  <p>
                    {navigation === "trackpad" ? (
                      <>
                        {t("sceneHelpTrackpadPan")}
                        <br />
                        {t("sceneHelpTrackpadZoom")}
                        <br />
                        {t("sceneHelpTrackpadOrbit")}
                        <br />
                        {t("sceneHelpTrackpadDrag")}
                      </>
                    ) : (
                      <>
                        {t("sceneHelpMouseOrbit")}
                        <br />
                        {t("sceneHelpMousePan")}
                        <br />
                        {t("sceneHelpMouseZoom")}
                      </>
                    )}
                  </p>
                  <p>
                    {t("sceneHelpModes")}
                  </p>
                  {/* **键位表就放在这里。** 快捷键不写出来等于没有 —— 而这一页照的是 Blender
                      的手势,用惯了的人会去试,没用过的人得有一处能看见。 */}
                  <strong>{t("sceneShortcuts")}</strong>
                  <dl className="scene-keymap">
                    <dt><KbdGroup keys={["G", "R", "S"]} /></dt><dd>{t("sceneKeyTransform")}</dd>
                    <dt><KbdGroup keys={["I", "⌥I"]} /></dt><dd>{t("sceneKeyInsert")}</dd>
                    <dt><KbdGroup keys={[t("sceneKeySpace")]} /></dt><dd>{t("sceneKeyPlay")}</dd>
                    <dt><KbdGroup keys={["←", "→"]} /></dt><dd>{t("sceneKeyStep")}</dd>
                    <dt><KbdGroup keys={["↑", "↓"]} /></dt><dd>{t("sceneKeyJump")}</dd>
                    <dt><KbdGroup keys={["⇧D"]} /></dt><dd>{t("sceneKeyDuplicate")}</dd>
                    <dt><KbdGroup keys={["X"]} /></dt><dd>{t("sceneKeyDelete")}</dd>
                    <dt><KbdGroup keys={["H", "⌥H"]} /></dt><dd>{t("sceneKeyHide")}</dd>
                    <dt><KbdGroup keys={["F"]} /></dt><dd>{t("sceneKeyFocus")}</dd>
                    <dt><KbdGroup keys={["⌘Z", "⇧⌘Z"]} /></dt><dd>{t("sceneKeyUndo")}</dd>
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
                  {t("cancel")}
                </Button>
              )}
            </div>
          )}
          {/* **时间条常驻。** 运镜和走位在同一条时间轴上,而"物体在第几秒在哪儿"这件事
              没有时间条就无从表达 —— 它不该藏在某个步骤后面。 */}
          <section className="scene-timeline" aria-label={t("scenePlaybackControls")}>
              {/* **关键帧视图:按物体分行,位置即时间。** 此前这里只画当前机位的那一条轨 ——
                  而场景里的物体和运镜共用同一条时间轴,只画相机的话,"第 3 秒人走到门口、
                  同一刻镜头推进"这件事在界面上没有位置可以表达。时间滑块收进它的标尺行,
                  两者共用一条横轴才对得齐。 */}
              <SceneDopeSheet
                controls={<div className="scene-shot-row">
                {/* 这一行和右边的打帧、缩放同处一条工具栏,**用同一套 xs 刻度**:28px 的
                    icon-xs 按钮、h-7 的选择框。此前这里是 32px 的 scene-tool 加一枚悬在外面的
                    16px 相机图标,和同行的按钮差着一档,图标也和选择框各是各的盒子。 */}
                <Pick
                  label={t("sceneCurrentShot")}
                  value={shot.id}
                  options={draft.content.shots.map((s) => [s.id, s.name])}
                  size="xs"
                  className="w-[150px] min-w-[70px] shrink"
                  icon={<Camera size={14} className="shrink-0 text-muted-foreground" />}
                  onChange={(id) => {
                    setShotId(id);
                    setTime(0);
                    setPlaying(false);
                  }}
                />
                <Button
                  size="icon-xs"
                  variant="outline"
                  title={t("sceneNewShot")}
                  aria-label={t("sceneNewShot")}
                  disabled={draft.content.shots.length >= 32}
                  onClick={() => {
                    // 新建镜头 = 新建一台机位 + 一个用它的镜头。**它们成对出现** ——
                    // 镜头必须指向一台真实存在的相机。机位停在你当前看的那个视角上。
                    const here = view.current!.camera();
                    const { camera, shot: s } = makeShot(
                      t("sceneShotName").replace("{n}", String(draft.content.shots.length + 1)),
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
                  <Plus />
                </Button>
                {/* 删镜头连同它的机位(见 removeShot)。此前没有这个入口,于是「新建镜头」建出来
                    的机位在物体列表里怎么都删不掉。最后一个镜头不能删 —— 场景至少要有一个。 */}
                <Button
                  size="icon-xs"
                  variant="outline"
                  title={t("sceneDeleteShot")}
                  aria-label={t("sceneDeleteShot")}
                  disabled={draft.content.shots.length <= 1 || !!busy}
                  onClick={() => {
                    const at = draft.content.shots.indexOf(shot);
                    const next = removeShot(draft.content, shot.id);
                    update(next);
                    setShotId(next.shots[Math.max(0, at - 1)].id);
                    setTime(0);
                    setPlaying(false);
                  }}
                >
                  <Minus />
                </Button>
                <span className="scene-tool-divider" aria-hidden="true" />
                <Button size="icon-xs" variant="ghost" title={t("sceneGoToStart")} aria-label={t("sceneGoToStart")} onClick={() => { setTime(0); setPlaying(false); }}><ChevronFirst /></Button>
                <Button
                  size="icon-xs"
                  variant="ghost"
                  title={playing ? t("scenePause") : t("scenePlayShot")}
                  aria-label={playing ? t("scenePause") : t("scenePlayShot")}
                  disabled={!!busy}
                  onClick={togglePlayback}
                >
                  {playing ? <Pause /> : <Play />}
                </Button>
                <Button size="icon-xs" variant="ghost" title={t("sceneGoToEnd")} aria-label={t("sceneGoToEnd")} onClick={() => { setTime(shot.duration); setPlaying(false); }}><ChevronLast /></Button>
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
                  title={t("sceneObjects")}
                  count={draft.content.objects.length}
                  actions={
                    <>
                    {/* **一键收拢/展开。** 79 个物体摊平是一屏翻不完的列表,而一个个点箭头收
                        同样难受。按钮的语义跟着当前状态走:还有组开着就是「全部收起」,全收起了
                        才变成「全部展开」—— 一个按钮两种意思,但任何时刻它只表示其中一种,
                        而那一种正是你此刻想要的。没有组时不出现(它没有可操作的对象)。 */}
                    {groupIds.length > 0 && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title={allCollapsed ? t("sceneExpandAllGroups") : t("sceneCollapseAllGroups")}
                        aria-label={allCollapsed ? t("sceneExpandAllGroups") : t("sceneCollapseAllGroups")}
                        onClick={() => setCollapsed(allCollapsed ? new Set() : new Set(groupIds))}
                      >
                        {allCollapsed ? <ChevronsUpDown size={15} /> : <ChevronsDownUp size={15} />}
                      </Button>
                    )}
                    {/* 用 SearchableSelect 而不是手写弹层:物体种类只会越来越多,而手写那个
                        既不分组、又没有高度上限(十几项就把屏幕撑满)、也搜不了。这颗控件
                        本来就是给"选项多到普通 Select 会溢出屏幕"准备的。 */}
                    <SearchableSelect
                      value=""
                      onValueChange={(kind) => {
                        if (kind === "__import__") file.current?.click();
                        else if (kind.startsWith(MODEL_PREFIX)) {
                          const id = kind.slice(MODEL_PREFIX.length);
                          const m = sceneModels.data?.find((one) => one.id === id);
                          if (m) placeModel(m.name, m.id);
                        } else add(kind as SceneObject["kind"]);
                      }}
                      searchPlaceholder={t("sceneSearchKinds")}
                      emptyText={t("sceneNoKindMatches")}
                      options={addOptions}
                      trigger={
                        <Button variant="ghost" size="icon-sm" title={t("sceneAddObject")} aria-label={t("sceneAddObject")}>
                          <Plus size={16} />
                        </Button>
                      }
                    />
                    </>
                  }
                >
                  {!draft.content.objects.length && (
                    <div className="scene-start">
                      <Box size={28} strokeWidth={1.4} />
                      <strong>{t("sceneStartTitle")}</strong>
                      <p>{t("sceneStartBody")}</p>
                    </div>
                  )}
                  {/* **按树的顺序画,缩进按层数来。** 此前是数组原样铺开、缩进写成
                      `o.parent_id ? 24 : 10` —— 只有两级,组里再放组和它的兄弟一样平;
                      而把一个物体移进组之后那一行也不会挪到组下面,看上去像没生效。 */}
                  <div className="scene-object-list" role="tree" aria-label={t("sceneObjects")}>
                    {objectTree(draft.content, collapsed).map(({ object: o, depth, children }) => (
                      <div
                        className="scene-object-row"
                        key={o.id}
                        // 淡显的是"实际看不见"的行,不只是自己藏了的:藏一个组,组里那些行也要
                        // 看得出它们此刻不在画面里。`self` 与 `inherited` 分开,前者另加斜体 ——
                        // 眼睛图标只说自己那一位,斜体说的是"是我自己藏的"。
                        data-hidden={o.hidden ? "self" : hiddenIds.has(o.id) ? "inherited" : undefined}
                        role="treeitem"
                        aria-level={depth + 1}
                        aria-expanded={children ? !collapsed.has(o.id) : undefined}
                        // 缩进只经过这一个值:行的左内距按它算(见 scenes.css 里那段)。
                        style={{ "--depth": depth } as React.CSSProperties}
                      >
                        {/* 有孩子才给折叠箭头:79 个物体摊平是一屏翻不完的列表,收起来之后
                            它就是八行。没孩子的留一块同宽的空位,名字才对得齐。 */}
                        {children ? (
                          <button
                            className="scene-object-twist"
                            aria-label={t(collapsed.has(o.id) ? "sceneExpandNamed" : "sceneCollapseNamed").replace("{name}", o.name)}
                            onClick={() =>
                              setCollapsed((was) => {
                                const next = new Set(was);
                                if (!next.delete(o.id)) next.add(o.id);
                                return next;
                              })
                            }
                          >
                            <ChevronRight
                              size={13}
                              style={{
                                transform: collapsed.has(o.id) ? undefined : "rotate(90deg)",
                              }}
                            />
                          </button>
                        ) : (
                          <span className="scene-object-twist" />
                        )}
                        <button
                          className="scene-object-name"
                          aria-pressed={selected === o.id}
                          onClick={() => {
                            setSelected(o.id);
                            setPreview(false);
                            requestAnimationFrame(() => view.current?.focus());
                          }}
                          onDoubleClick={() => view.current?.focus()}
                        >
                          <ObjectKindIcon kind={o.kind} />
                          <span>{o.name}</span>
                          {children > 0 && collapsed.has(o.id) && <small>{t("sceneChildCount").replace("{n}", String(children))}</small>}
                        </button>
                        {/* 显示/隐藏和删除并排,同尺寸、同一种安静的样子 —— 此前藏一个物体要先选中它,
                            再到下面的「调整对象」里找那颗眼睛;列表里只有一个「隐藏」字样的标记。 */}
                        <button
                          className="scene-object-visibility"
                          aria-label={t(o.hidden ? "sceneShowObjectNamed" : "sceneHideObjectNamed").replace("{name}", o.name)}
                          title={t(o.hidden ? "sceneShowObjectNamed" : "sceneHideObjectNamed").replace("{name}", o.name)}
                          disabled={!!busy}
                          onClick={() => toggleHidden(o.id)}
                        >
                          {o.hidden ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                        <button
                          className="scene-object-delete"
                          aria-label={t("sceneDeleteObjectNamed").replace("{name}", o.name)}
                          title={t("sceneDeleteNamed").replace("{name}", o.name)}
                          disabled={!!busy}
                          onClick={() => removeSceneObjects([o.id])}
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

                <ScenePanel id="inspector" title={object ? t("sceneAdjustObject") : t("sceneAppearance")}>
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
                    onRemove={removeSceneObjects}
                    setSelected={setSelected}
                  />
                </ScenePanel>
            </>
            {/* **镜头设置跟着「选中了哪台机位」走。** 相机现在是场景里的物体,它的运镜、
                时长、比例本来就该在选中它时出现 —— 而不是藏在一个叫「设计镜头」的步骤后面。 */}
            {object?.kind === "camera" && rig && object.id === rig.id && (
              <ScenePanel id="camera" title={t("sceneShotSettings")}>
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
                applyView={() => applyCameraPose(view.current!.camera())}
                onPose={applyCameraPose}
                pose={posing === rig.id ? rig : undefined}
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
              contextLine={t("sceneAgentContext").replace("{sceneId}", initial.id).replace("{workspaceId}", initial.workspace_id)}
              emptyHint={t("sceneAssistantEmpty")}
              placeholder={t("sceneAssistantPlaceholder")}
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
