import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, horizontalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, ExternalLink, Pause, Play, Scissors, Trash2, Volume2, VolumeX } from "lucide-react";
import React from "react";
import { toast } from "sonner";

import { assetFileUrl, assetThumbnailUrl } from "@/api/domains/assets";
import { getSequence, moveClipsBatch, rippleDeleteClipsBatch, splitClip, type Clip, type Sequence } from "@/api/domains/editor";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";
import { isImeKeystroke } from "@/lib/shortcuts";
import { noteSequenceEdit, readSequenceCursor, updateSequenceCursor, useSequenceCursor } from "@/features/boards/sequenceCursor";

/** 贴着格子外壳内沿上半的圆角(和 boardNodes 的 CELL_INNER_TOP_RADIUS 同一个值:外壳 rounded-xl 减 1px 边框)。 */
const CELL_INNER_TOP_RADIUS = "rounded-t-[calc(var(--radius-xl)-1px)]";

/** 时间线格读的那条时间线。连线加片段、剪刀、删除都拿回整条时间线,写回这一份缓存。 */
export const boardSequenceKey = (sequenceId: string) => ["board-sequence", sequenceId] as const;

/** 缩略图条上一秒多宽(像素)。每段至少 44 像素,短镜头也点得中。 */
const PIXELS_PER_SECOND = 22;
const MIN_TILE = 44;

const span = (clip: Clip) => (clip.src_out - clip.src_in) / (clip.speed || 1);
const end = (clip: Clip) => clip.timeline_start + span(clip);

/** 主视频轨(第一条视频轨)和第一条音频轨上的片段,按先后。连线接进来的就落在这两条上(后端 sequences.append)。 */
function mainTracks(sequence: Sequence | undefined) {
  const tracks = [...(sequence?.tracks ?? [])].sort((a, b) => a.position - b.position);
  const sorted = (kind: string) =>
    [...(tracks.find((track) => track.kind === kind)?.clips ?? [])]
      .filter((clip) => clip.asset_id)
      .sort((a, b) => a.timeline_start - b.timeline_start);
  return { video: sorted("video"), audio: sorted("audio") };
}

function clipAt(clips: Clip[], time: number): Clip | undefined {
  return clips.find((clip) => clip.timeline_start <= time && time < end(clip));
}

const GAP = 2;
const PADDING = 6;
/** 按下一段之后挪过这么多像素才算拖动(否则是点选)。 */
const DRAG_THRESHOLD = 4;

/** 一段拖到另一段的位置上之后的新先后;没挪(或落回原处)就是 null。 */
export function reorderedClips(clips: Clip[], activeId: string, overId: string | null | undefined): Clip[] | null {
  const from = clips.findIndex((clip) => clip.id === activeId);
  const to = clips.findIndex((clip) => clip.id === overId);
  if (from < 0 || to < 0 || from === to) return null;
  return arrayMove(clips, from, to);
}

/** 缩略图条上每一段的位置:按先后排,宽度跟时长走(有最小宽度)。播放头和点击都经它换算,不按统一的每秒几像素算 ——
 *  短镜头被撑宽之后,统一换算会让播放头和画面对不上。 */
export function stripLayout(clips: Clip[]) {
  let x = PADDING;
  const tiles = clips.map((clip) => {
    const width = Math.max(MIN_TILE, span(clip) * PIXELS_PER_SECOND);
    const tile = { clip, x, width };
    x += width + GAP;
    return tile;
  });
  const toX = (time: number) => {
    const tile = tiles.find(({ clip }) => time < end(clip)) ?? tiles.at(-1);
    if (!tile) return PADDING;
    const ratio = Math.min(1, Math.max(0, (time - tile.clip.timeline_start) / span(tile.clip)));
    return tile.x + ratio * tile.width;
  };
  const toTime = (position: number) => {
    const tile = tiles.find(({ x: left, width }) => position < left + width + GAP) ?? tiles.at(-1);
    if (!tile) return 0;
    const ratio = Math.min(1, Math.max(0, (position - tile.x) / tile.width));
    return tile.clip.timeline_start + ratio * span(tile.clip);
  };
  return { tiles, toX, toTime };
}

/**
 * 时间线格的身子(ADR 0030):上半粗剪预览,下半缩略图条,左边一列工具(剪刀、删除、在剪辑里打开)。
 *
 * **预览是粗剪预览,不是成片渲染** —— 按主视频轨的顺序连着播画面、第一条音频轨跟着响;变换、调色、字幕在剪辑页和
 * 导出里才完整。剪辑页的监视器绑着全局的剪辑状态,一张画板上可能有好几格时间线,所以这里另起一个只管拼接的小播放器。
 * 格子里的每一步都是那条时间线上的正常操作(切开、删除、换顺序),在剪辑页里能撤销、能接着改;在画板上按 ⌘Z 也撤得回来
 * (每一步做成后 noteSequenceEdit,画板把它记进自己的撤销栈)。
 */
export function SequenceCell({ sequenceId }: { sequenceId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const sequence = useQuery({ queryKey: boardSequenceKey(sequenceId), queryFn: () => getSequence(sequenceId), retry: false });
  const { video, audio } = React.useMemo(() => mainTracks(sequence.data), [sequence.data]);
  const strip = React.useMemo(() => stripLayout(video), [video]);
  const total = Math.max(0, ...video.map(end), ...audio.map(end));

  //: 播放头和选中的那一段和上方操作条共用(剪刀、删除在那儿),见 sequenceCursor。
  const { time, picked } = useSequenceCursor(sequenceId);
  const setTime = (next: number) => updateSequenceCursor(sequenceId, { time: next });
  const setPicked = (next: string | null) => updateSequenceCursor(sequenceId, { picked: next });
  const [playing, setPlaying] = React.useState(false);
  const [muted, setMuted] = React.useState(false);
  //: 正在拖的那一段和拖动开始时的画布缩放(见 SortableTile)。
  const [dragging, setDragging] = React.useState<{ id: string; zoom: number } | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: DRAG_THRESHOLD } }));
  const scrubbing = React.useRef(false);
  const stripRef = React.useRef<HTMLDivElement | null>(null);

  //: 播放:按真实时间往前走,走到头停。画面、声音各自按「这一刻该在哪一段的哪一秒」跟上。
  React.useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const step = (now - last) / 1000;
      last = now;
      const next = readSequenceCursor(sequenceId).time + step;
      if (next >= total) {
        updateSequenceCursor(sequenceId, { time: total });
        setPlaying(false);
        return;
      }
      updateSequenceCursor(sequenceId, { time: next });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, total, sequenceId]);

  const shown = clipAt(video, time);
  const heard = clipAt(audio, time);
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  //: 播着的时候每秒校一次(换段时立刻校),拖播放头时每一下都校。
  const coarse = playing ? Math.floor(time) : time;
  React.useEffect(() => {
    for (const [element, clip] of [[videoRef.current, shown], [audioRef.current, heard]] as const) {
      if (!element || !clip) continue;
      const target = clip.src_in + (time - clip.timeline_start) * (clip.speed || 1);
      if (!playing || Math.abs(element.currentTime - target) > 0.3) element.currentTime = target;
      element.playbackRate = clip.speed || 1;
      if (playing) void element.play().catch(() => undefined);
      else element.pause();
    }
  }, [shown?.id, heard?.id, playing, coarse]);

  const settle = (next: Sequence) => qc.setQueryData(boardSequenceKey(sequenceId), next);
  const fail = (error: unknown) => toast.error(errorText(error));
  const actions = useSequenceActions(sequenceId);
  const reorder = useMutation({
    mutationFn: (order: Clip[]) => {
      //: 按新的先后首尾相接重新排(和剪辑页的波纹一样,中间不留空当)。一次提交,一步撤销。
      let cursor = 0;
      const moves = order.map((clip) => {
        const move = { clip_id: clip.id, timeline_start: cursor };
        cursor += span(clip);
        return move;
      });
      return moveClipsBatch(sequenceId, moves);
    },
    onSuccess: (next) => {
      settle(next);
      noteSequenceEdit(sequenceId);
    },
    onError: fail,
  });

  const pickedClip = video.find((clip) => clip.id === picked);

  /** 条上的横坐标(条自己的像素,已按画布缩放折回、算上横向滚动)。画布缩放时屏幕像素和条的像素不是一回事。 */
  const stripX = (clientX: number) => {
    const element = stripRef.current;
    if (!element) return 0;
    const box = element.getBoundingClientRect();
    const scale = element.offsetWidth ? box.width / element.offsetWidth : 1;
    return (clientX - box.left) / (scale || 1) + element.scrollLeft;
  };
  const seek = (clientX: number) => setTime(Math.max(0, Math.min(total, strip.toTime(stripX(clientX)))));
  const dropped = ({ active, over }: DragEndEvent) => {
    setDragging(null);
    const order = reorderedClips(video, String(active.id), over ? String(over.id) : null);
    if (order) reorder.mutate(order);
  };

  if (sequence.isError) {
    return (
      <div data-sequence-missing="" className="grid min-h-0 flex-1 place-items-center px-4 text-center text-ui-xs text-muted-foreground">
        {t("boardSequenceMissing")}
      </div>
    );
  }

  //: **只有条和按钮吞掉指针**(nodrag / nopan;滚轮一律交给画布):预览那一大块照常能拖着整格走 —— 此前整个身子都标了
  //: nodrag,只剩上面那行小字抓得住(用户:「无法拖动」)。
  return (
    <div
      data-sequence-cell=""
      className="flex min-h-0 flex-1 flex-col"
      tabIndex={-1}
      onKeyDown={(event) => {
        if ((event.key === "Delete" || event.key === "Backspace") && pickedClip) {
          event.stopPropagation();
          actions.remove();
        }
      }}
    >
      <div className={cn("relative min-h-0 flex-1 overflow-hidden", CELL_INNER_TOP_RADIUS, shown ? "bg-black" : "bg-secondary/40")}>
        {shown ? (
          shown.asset_kind === "image" ? (
            <img src={assetFileUrl(shown.asset_id ?? "")} alt="" className="h-full w-full object-contain" draggable={false} />
          ) : (
            <video
              key={shown.id}
              ref={videoRef}
              src={assetFileUrl(shown.asset_id ?? "")}
              muted={muted}
              playsInline
              preload="auto"
              className="h-full w-full object-contain"
            />
          )
        ) : (
          <div data-sequence-empty="" className="grid h-full place-items-center px-6 text-center text-muted-foreground">
            <span className="grid justify-items-center gap-2">
              <Clapperboard size={28} strokeWidth={1.2} />
              <span className="text-ui-xs">{video.length === 0 ? t("boardSequenceEmpty") : ""}</span>
            </span>
          </div>
        )}
        {heard && (
          <audio key={heard.id} ref={audioRef} src={assetFileUrl(heard.asset_id ?? "")} muted={muted} preload="auto" />
        )}
        {total > 0 && (
          <div className="nodrag nopan absolute inset-x-0 bottom-0 flex items-center gap-1.5 bg-gradient-to-t from-black/70 to-transparent px-2.5 pb-2 pt-8 text-white">
            <button
              type="button"
              aria-label={playing ? t("boardSequencePause") : t("boardSequencePlay")}
              onClick={() => {
                if (!playing && time >= total) setTime(0);
                setPlaying((on) => !on);
              }}
              className="grid h-7 w-7 cursor-pointer place-items-center rounded-full border-0 bg-white/15 text-white hover:bg-white/25"
            >
              {playing ? <Pause size={13} /> : <Play size={13} className="translate-x-px" />}
            </button>
            <span data-sequence-time="" className="text-ui-xs tabular-nums">
              {time.toFixed(1)}s <span className="text-white/60">/ {total.toFixed(1)}s</span>
            </span>
            <span className="flex-1" />
            <span className="truncate text-ui-2xs text-white/55" title={t("boardSequenceRoughCut")}>{t("boardSequenceRoughCut")}</span>
            <button
              type="button"
              aria-label={muted ? t("boardSequenceUnmute") : t("boardSequenceMute")}
              onClick={() => setMuted((on) => !on)}
              className="grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full border-0 bg-transparent text-white hover:bg-white/15"
            >
              {muted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
          </div>
        )}
      </div>

      <div className="flex h-[76px] shrink-0 items-stretch border-t border-border p-2">
        <div
          ref={stripRef}
          data-sequence-strip=""
          //: **不标 nowheel**:触控板双指平移画布经过这条时不能停(用户:「画布拖动到时间线的这个位置会暂停」)。
          //: 条长出格子时用 Shift + 滚轮或拖播放头看后面的段。空条里没有可拖的段:不吞指针,拖着它照样平移画布。
          //: 条的空白处是点一下跳过去,不是文字:不给文本光标(用户:「播放头上为何是文本鼠标样式」)。
          className={cn("relative min-w-0 flex-1 touch-none select-none overflow-x-auto rounded-md bg-secondary/50",
                        video.length > 0 && "nodrag nopan cursor-pointer")}
          onPointerDown={(event) => {
            if (video.length === 0) return;
            //: 按在空白处或播放头上 = 拖播放头;按在某一段上由拖动库处理(点一下选中,拖着换顺序)。
            if ((event.target as HTMLElement).closest("[data-sequence-clip]")) return;
            event.currentTarget.setPointerCapture?.(event.pointerId);
            scrubbing.current = true;
            seek(event.clientX);
          }}
          onPointerMove={(event) => {
            if (scrubbing.current) seek(event.clientX);
          }}
          onPointerUp={() => {
            scrubbing.current = false;
          }}
          onPointerCancel={() => {
            scrubbing.current = false;
          }}
        >
          {video.length === 0 ? (
            <div className="grid h-full place-items-center px-3 text-center text-ui-2xs text-muted-foreground">
              {t("boardSequenceStripEmpty")}
            </div>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragStart={({ active }) => {
                //: 格子在画布里是缩放过的:拖动库量的是屏幕像素,段自己挪的是条里的像素,开拖时记下两者之比。
                const element = stripRef.current;
                const zoom = element?.offsetWidth ? element.getBoundingClientRect().width / element.offsetWidth : 1;
                setDragging({ id: String(active.id), zoom: zoom || 1 });
              }}
              onDragEnd={dropped}
              onDragCancel={() => setDragging(null)}
            >
              <SortableContext items={video.map((clip) => clip.id)} strategy={horizontalListSortingStrategy}>
                <div className="relative flex h-full items-center gap-0.5 px-1.5 py-1.5">
                  {strip.tiles.map(({ clip, width }) => (
                    <SortableTile
                      key={clip.id}
                      clip={clip}
                      width={width}
                      zoom={dragging?.zoom ?? 1}
                      picked={picked === clip.id}
                      onPick={(clientX) => {
                        //: 点一下(没拖):选中这一段,播放头跳到点的地方。
                        setPicked(clip.id);
                        if (clientX !== null) seek(clientX);
                      }}
                    />
                  ))}
                  {!dragging && (
                    //: 播放头:一根贴满条高的线,顶上一个圆点手柄;白描边 + 阴影,压在任何缩略图上都看得见。
                    //: 线两侧各留几像素的抓取区,按住左右拖(按下落到条上,走拖播放头那条路)。
                    <span data-sequence-playhead="" aria-hidden="true" className="absolute inset-y-0 w-3 -translate-x-1/2 cursor-ew-resize"
                          style={{ left: strip.toX(time) }}>
                      <span className="pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 bg-primary shadow-[0_0_0_1px_rgba(255,255,255,0.85),0_1px_4px_rgba(0,0,0,0.35)]" />
                      <span className="pointer-events-none absolute top-0 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full border-2 border-white bg-primary shadow-md" />
                    </span>
                  )}
                </div>
              </SortableContext>
            </DndContext>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * 缩略图条上的一段:按住横着拖换顺序(@dnd-kit/sortable),点一下选中。
 *
 * 拖动库给的位移是屏幕像素,段却画在缩放过的画布里:按开拖时量到的缩放折回去,否则画布缩小时段跑得比指针快。
 * 只许横着挪。
 */
function SortableTile({ clip, width, zoom, picked, onPick }: {
  clip: Clip;
  width: number;
  zoom: number;
  picked: boolean;
  onPick: (clientX: number | null) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: clip.id });
  const moved = transform ? { ...transform, x: transform.x / zoom, y: 0, scaleX: 1, scaleY: 1 } : null;
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      data-sequence-clip={clip.id}
      aria-pressed={picked}
      title={`${span(clip).toFixed(1)}s`}
      onClick={(event) => onPick(event.clientX)}
      onKeyDown={(event) => {
        if (isImeKeystroke(event)) return;
        if (event.key === "Enter" || event.key === " ") onPick(null);
      }}
      style={{
        width,
        transform: CSS.Transform.toString(moved),
        transition,
        backgroundImage: `url(${assetThumbnailUrl(clip.asset_id ?? "")})`,
      }}
      className={cn(
        "relative h-full shrink-0 cursor-grab rounded bg-secondary bg-cover bg-center outline-none",
        picked && "ring-2 ring-inset ring-primary",
        isDragging && "z-10 cursor-grabbing opacity-80 shadow-lg ring-2 ring-primary",
      )}
    />
  );
}

/**
 * 一格时间线的剪刀、删除:按的是那一格此刻的播放头和选中的那一段(sequenceCursor)。操作条上的按钮和格子里的
 * Delete 键走同一份。
 */
export function useSequenceActions(sequenceId: string) {
  const qc = useQueryClient();
  const sequence = useQuery({ queryKey: boardSequenceKey(sequenceId), queryFn: () => getSequence(sequenceId), retry: false });
  const { time, picked } = useSequenceCursor(sequenceId);
  const { video } = mainTracks(sequence.data);
  const shown = clipAt(video, time);
  //: 剪刀切的是播放头所在的那一段;播放头落在段的边上时没什么可切。
  const cuttable = shown && time - shown.timeline_start > 0.05 && end(shown) - time > 0.05 ? shown : undefined;
  const pickedClip = video.find((clip) => clip.id === picked);
  const settle = (next: Sequence) => qc.setQueryData(boardSequenceKey(sequenceId), next);
  const fail = (error: unknown) => toast.error(errorText(error));
  const cut = useMutation({
    mutationFn: (clip: Clip) => splitClip(sequenceId, clip.id, clip.src_in + (time - clip.timeline_start) * (clip.speed || 1)),
    onSuccess: (next) => {
      settle(next);
      noteSequenceEdit(sequenceId);
    },
    onError: fail,
  });
  const removal = useMutation({
    mutationFn: (clipId: string) => rippleDeleteClipsBatch(sequenceId, [clipId]),
    onSuccess: (next) => {
      settle(next);
      updateSequenceCursor(sequenceId, { picked: null });
      noteSequenceEdit(sequenceId);
    },
    onError: fail,
  });
  return {
    canCut: Boolean(cuttable) && !cut.isPending,
    cut: () => cuttable && cut.mutate(cuttable),
    canRemove: Boolean(pickedClip) && !removal.isPending,
    remove: () => pickedClip && removal.mutate(pickedClip.id),
    editorHref: sequence.data ? `#/editor?p=${encodeURIComponent(sequence.data.project_id)}&s=${encodeURIComponent(sequenceId)}` : undefined,
  };
}

/** 时间线格上方操作条里的那几枚:剪刀、删除、在剪辑里打开。样子和操作条上别的按钮一样,由操作条传进来。 */
export function SequenceToolbarActions({ sequenceId, button }: {
  sequenceId: string;
  button: (props: { label: string; icon: React.ReactNode; onClick?: () => void; disabled?: boolean; href?: string; marker: string }) => React.ReactNode;
}) {
  const t = useI18n();
  const actions = useSequenceActions(sequenceId);
  return (
    <>
      {button({ label: t("boardSequenceCut"), icon: <Scissors size={13} />, onClick: actions.cut, disabled: !actions.canCut, marker: "cut" })}
      {button({ label: t("boardSequenceDelete"), icon: <Trash2 size={13} />, onClick: actions.remove, disabled: !actions.canRemove, marker: "delete" })}
      {button({ label: t("boardSequenceOpen"), icon: <ExternalLink size={13} />, href: actions.editorHref, marker: "open" })}
    </>
  );
}
