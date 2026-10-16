import * as React from "react";

import type { Shot, ShotMotionTrack } from "@/api/domains/shots";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Hint } from "@/components/ui/tooltip";
import { formatTimecode } from "@/lib/time";
import { isImeKeystroke } from "@/lib/shortcuts";

/**
 * 「镜头」块**上面**那条节奏条:把整条动静曲线画出来(ADR 0061 §5 后端那一半的界面)。
 *
 * ## 它画的是什么
 *
 * 横轴 = 整段时长,纵轴 = 帧间差(0–255);刀口按 `shots[].start` / `end` 分格,当前镜跟着播放位置
 * 高亮,点某一镜就跳到那一镜的开头 —— 跳转**不自己碰播放器**:报一个秒数给外面(详情把它交给左栏
 * 那个 `MediaPreviewPlayer`,和逐镜列表同一颗 `seekTo`,不另造第二个机制)。
 *
 * ## 三件容易画错的事,都写在这里
 *
 * 1. **一万八千个点画进几百像素**:一列(1px)一个采样窗口,取**窗口最大值** —— 取平均会把一帧的
 *    强动(一个尖峰)摊平到整段里,看上去什么都没发生。1 小时 ≈ 18000 个点 / 几百列,一列几十个点。
 * 2. **时间轴不是 `i / hz`**:`values[i]` 在 `first_sample_seconds + i × sample_interval_seconds` 秒
 *    (后端 `ShotMotionTrackResponse` 的原话;第 0 个采样不在 0 秒 —— `tblend` 的第 0 帧没有前一帧)。
 *    两个数都从响应里读,不自己拿 `hz` 反推。
 * 3. **曲线只是看的,取不到不该挡住别的**:`status` 是 `none`(没量过 / 老行没记)就说一句拆一次
 *    就有;`missing`(库里记着 `points` 与 `digest`,盘上那份没了或被改过)说出来并给重拆的出口 ——
 *    两种都不是错误,也不是 404。
 *
 * ## 无障碍
 *
 * 每一镜在条上是一个可聚焦的 `role="button"`(说明里有镜号、起止、时长、实测动静),回车 / 空格
 * 都跳 —— 和底下那列逐镜的行一样走得到;悬停走 `Hint`(和全站同一条说明)。
 */

/** 帧间差的上限(YAVG 0–255)—— 纵轴满格就是它。 */
export const PACE_MOTION_MAX = 255;
/**
 * 纵轴最低按这个满格画。动静本来就很小的片子(整片峰值 6)按 255 画是一条贴着底的线,看不出节奏;
 * 抬高之后**必须**把「满格 {值}」写出来,不然读者会把它当成 255 的比例。
 */
export const PACE_MIN_SCALE = 32;
/** 量不出宽度时的一档(jsdom 没有版面、容器还没挂上)—— 和量出来的宽度走同一条画法。 */
export const PACE_FALLBACK_COLUMNS = 600;
/** 条窄到几十像素时一列已经不是一个像素了,再少就没法看;太宽也只画这么多(多出来的列是白算)。 */
const PACE_MIN_COLUMNS = 48;
const PACE_MAX_COLUMNS = 2400;
/** 纵轴的刻度数(SVG 的坐标高,和像素高无关 —— 像素高由 CSS 定)。 */
const PACE_ROWS = 32;

/** 采样时刻用的那个间隔:响应里没有(老版本 / 空曲线)时按约定退到 `1/hz`。 */
function paceInterval(track: ShotMotionTrack): number {
  const interval = Number(track.sample_interval_seconds);
  if (Number.isFinite(interval) && interval > 0) return interval;
  const hz = Number(track.hz);
  return Number.isFinite(hz) && hz > 0 ? 1 / hz : 0;
}

/** 第 `index` 个采样在哪一秒:`first_sample_seconds + index × sample_interval_seconds`(约定见文件头)。 */
export function paceSampleSeconds(track: ShotMotionTrack, index: number): number {
  const interval = paceInterval(track);
  const first = Number(track.first_sample_seconds);
  return (Number.isFinite(first) && first > 0 ? first : interval) + index * interval;
}

/** 第几秒落在第几列(0 起,夹在条内)。 */
export function paceColumn(seconds: number, duration: number, columns: number): number {
  if (!(duration > 0) || !(columns > 0) || !Number.isFinite(seconds)) return 0;
  return Math.min(columns - 1, Math.max(0, Math.floor((seconds / duration) * columns)));
}

/**
 * 曲线 → 每一列的**最大值**(0–255)。
 *
 * 采样密(18000 个点 / 几百列)时一列落进几十个点,取最大值:尖峰留住,取平均抹平。采样比列还稀时
 * 有的列没有点,那里是 0 —— 不补、不插值(补出来的线是画法编的,不是量到的)。
 */
export function paceColumns(track: ShotMotionTrack, duration: number, columns: number): number[] {
  const values = (track.values ?? []).map(Number);
  if (values.length === 0 || !(duration > 0) || !(columns > 0)) return [];
  const interval = paceInterval(track);
  const out = new Array<number>(columns).fill(0);
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index];
    if (!Number.isFinite(value)) continue;
    //: 两个时间字段都缺(空壳响应)时按采样均分 —— 至少让点落满整条,而不是全挤在第 0 列。
    const seconds = interval > 0 ? paceSampleSeconds(track, index) : (duration * (index + 0.5)) / values.length;
    const column = paceColumn(seconds, duration, columns);
    if (value > out[column]) out[column] = value;
  }
  return out;
}

/** 纵轴的满格:峰值,但不低于 `PACE_MIN_SCALE`(见它的说明)。 */
export function paceScale(peak: number): number {
  return Math.max(Number.isFinite(peak) && peak > 0 ? peak : 0, PACE_MIN_SCALE);
}

/** 播放位置落在哪一镜:区间是 `[start, end)`;还没进第一镜算第一镜,播过最后一镜算最后一镜。 */
export function paceCurrentShot(shots: Shot[], seconds: number): Shot | null {
  if (shots.length === 0) return null;
  const inside = shots.find((shot) => {
    const start = Number(shot.start) || 0;
    const end = Number(shot.end);
    return seconds >= start && (!Number.isFinite(end) || seconds < end);
  });
  if (inside) return inside;
  return seconds < (Number(shots[0].start) || 0) ? shots[0] : shots[shots.length - 1];
}

/** 摘要只给人看的短样子(`sha256:0123456789abcdef…` 太长,和镜头表里那些值一样只露头一截)。 */
export function shortDigest(digest: string): string {
  const text = String(digest || "");
  const prefix = text.startsWith("sha256:") ? "sha256:" : "";
  return `${prefix}${text.slice(prefix.length, prefix.length + 12)}`;
}

export function ShotPaceStrip({ shots, track, duration, playhead = 0, loading = false, error = "", onSeek, onRebuild }: {
  shots: Shot[];
  /** 整条曲线(`GET /assets/{id}/shots/track`)。还没取到是 `undefined`。 */
  track: ShotMotionTrack | undefined;
  /** 横轴满格(秒)—— 曲线覆盖的时长,取不到时用镜头表的末镜。 */
  duration: number;
  /** 播放器现在在第几秒(详情从 `MediaPreviewPlayer` 的 timeupdate 报上来)。 */
  playhead?: number;
  loading?: boolean;
  /** 这条请求自己的错(和镜头表那一份的错分开)。 */
  error?: string;
  /** 点某一镜:把它的 `start` 报上去,由详情交给左栏那个播放器。 */
  onSeek: (seconds: number) => void;
  /** `missing` 时的出口(和上面那颗「重拆镜头」同一条路)。有任务在跑时不给。 */
  onRebuild?: () => void;
}) {
  const t = useI18n();
  const lane = React.useRef<HTMLDivElement | null>(null);
  const columns = useLaneColumns(lane);
  //: 每列的最大值算一次就够:播放头一动就重渲(每秒几次),18000 个点不该跟着重算一遍。
  //: 三种 status 都要走这个 hook(不能在 return 之后才算),`none` / `missing` 给空数组。
  const values = React.useMemo(
    () => (track && track.status === "ready" ? paceColumns(track, duration, columns) : []),
    [track, duration, columns],
  );

  if (error) return <p data-shot-pace-status="error" className="text-ui-2xs leading-4 text-muted-foreground">{error}</p>;
  if (loading && !track) {
    return (
      <div data-shot-pace-status="loading" aria-hidden>
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (!track || track.status === "none") {
    return <p data-shot-pace-status="none" className="text-ui-2xs leading-4 text-muted-foreground">{t("shotPaceNoTrack")}</p>;
  }
  if (track.status === "missing") {
    return (
      <div data-shot-pace-status="missing" className="grid gap-1">
        <p className="text-ui-2xs leading-4 text-muted-foreground">
          {t("shotPaceMissing")
            .replaceAll("{points}", String(Number(track.points) || 0))
            .replace("{digest}", shortDigest(track.digest))}
        </p>
        {onRebuild ? (
          <Button size="xs" variant="outline" className="w-fit" onClick={onRebuild}>
            {t("shotBreakdownRedo")}
          </Button>
        ) : null}
      </div>
    );
  }

  if (values.length === 0) {
    return <p data-shot-pace-status="none" className="text-ui-2xs leading-4 text-muted-foreground">{t("shotPaceNoTrack")}</p>;
  }
  const peak = (track.values ?? []).reduce((high, value) => (Number.isFinite(value) && value > high ? value : high), 0);
  const scale = paceScale(peak);
  const current = paceCurrentShot(shots, playhead);
  const playheadColumn = paceColumn(playhead, duration, columns);
  const startColumn = (shot: Shot) => paceColumn(Number(shot.start) || 0, duration, columns);
  const endColumn = (shot: Shot) => paceColumn(Number(shot.end) || Number(shot.start) || 0, duration, columns);
  const mark = 1;
  //: 两位小数:小数尾巴随浮点飘,写进 DOM 会让断言(以及任何快照)跟着飘。
  const round = (value: number) => Math.round(value * 100) / 100;
  const detailOf = (shot: Shot) => t("shotPaceShotDetail")
    .replace("{shot}", shot.id)
    .replace("{start}", formatTimecode(Number(shot.start) || 0))
    .replace("{end}", formatTimecode(Number(shot.end) || Number(shot.start) || 0))
    .replace("{seconds}", (Number(shot.seconds) || 0).toFixed(1))
    .replace("{motion}", (Number(shot.motion) || 0).toFixed(1));

  return (
    <div data-shot-pace="" className="grid gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-ui-2xs font-medium text-muted-foreground">{t("shotPaceTitle")}</span>
        {/* 纵轴的刻度感:峰值始终报出来;整体动静小、纵轴抬高了满格,也要说清。 */}
        <span className="text-ui-2xs tabular-nums text-muted-foreground">
          {t("shotPacePeak").replace("{value}", String(round(peak)))}
          {scale > peak ? ` · ${t("shotPaceScale").replace("{value}", String(round(scale)))}` : ""}
        </span>
      </div>
      <div ref={lane} data-shot-pace-lane="" className="relative h-10 w-full overflow-hidden rounded-sm bg-workspace-subtle">
        <svg
          data-shot-pace-svg=""
          viewBox={`0 0 ${columns} ${PACE_ROWS}`}
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
          aria-hidden
        >
          {/* 当前镜:一整段底带 + 一条上沿 —— 曲线画在上面,底带不会把它盖掉。 */}
          {current ? (
            <>
              <rect
                data-pace-current={current.id}
                x={startColumn(current)}
                y={0}
                width={Math.max(mark, endColumn(current) - startColumn(current))}
                height={PACE_ROWS}
                className="fill-primary"
                opacity={0.22}
              />
              <rect
                x={startColumn(current)}
                y={0}
                width={Math.max(mark, endColumn(current) - startColumn(current))}
                height={2}
                className="fill-primary"
                opacity={0.9}
              />
            </>
          ) : null}
          {/* 曲线:一列(1px)一根,高度按窗口最大值 —— 尖峰不会被摊平。 */}
          {values.map((value, column) => (value > 0 ? (
            <rect
              key={column}
              data-pace-column={column}
              data-pace-value={round(value)}
              x={column}
              y={round(PACE_ROWS - (Math.min(value, scale) / scale) * PACE_ROWS)}
              width={1.02}
              height={round((Math.min(value, scale) / scale) * PACE_ROWS)}
              className="fill-primary"
              opacity={0.8}
            />
          ) : null))}
          {/* 刀口:每一镜的 start 一竖。 */}
          {shots.map((shot) => (
            <rect
              key={shot.id}
              data-pace-cut={shot.id}
              x={startColumn(shot)}
              y={0}
              width={mark}
              height={PACE_ROWS}
              className="fill-foreground"
              opacity={0.45}
            />
          ))}
          {/* 播放位置:一条细线(当前镜那一整段已经高亮了,这条给的是「精确到哪儿」)。 */}
          {playhead > 0 ? (
            <rect data-pace-playhead="" x={playheadColumn} y={0} width={mark} height={PACE_ROWS} className="fill-foreground" opacity={0.8} />
          ) : null}
        </svg>
        {/*
          条上的每一镜:盖在它那一段上,可点、可聚焦。**空的是有意的** —— 看得见的那份在 SVG 里,
          这一层是交互面;名字(镜号 / 起止 / 时长 / 实测动静)走 `aria-label` 和悬停说明。
        */}
        {shots.map((shot) => {
          const start = Number(shot.start) || 0;
          const left = startColumn(shot);
          const right = Math.max(left + 1, endColumn(shot));
          return (
            <Hint key={shot.id} label={detailOf(shot)} hint={t("shotPaceSeek")}>
              <div
                role="button"
                tabIndex={0}
                data-shot-region={shot.id}
                aria-label={detailOf(shot)}
                className="absolute inset-y-0 cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring"
                style={{ left: `${(left / columns) * 100}%`, width: `${((right - left) / columns) * 100}%` }}
                onClick={() => onSeek(start)}
                onKeyDown={(event) => {
                  //: 组词期间的回车 / 空格归输入法(和全站每一条 onKeyDown 同一条规矩)。
                  if (isImeKeystroke(event)) return;
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  onSeek(start);
                }}
              />
            </Hint>
          );
        })}
      </div>
      {/* 横轴的刻度感:首尾 + 刀口数(每条的准数在它自己的悬停 / 读屏说明里)。 */}
      <div className="flex items-baseline justify-between gap-2 text-ui-2xs tabular-nums text-muted-foreground">
        <span>{formatTimecode(0)}</span>
        <span>{t("shotPaceCuts").replace("{value}", String(shots.length))}</span>
        <span>{formatTimecode(duration)}</span>
      </div>
    </div>
  );
}

/**
 * 条有多少列 = 它有多少像素宽(「每 1px 取该窗口的最大值」里的那个 1px)。
 *
 * 量不出宽度时用 `PACE_FALLBACK_COLUMNS`(jsdom 没有版面、容器还没挂上),不量也能画 —— 只是列数
 * 是估的。没有 `ResizeObserver` 的环境(老浏览器、测试)只量那一次。
 */
function useLaneColumns(ref: React.RefObject<HTMLDivElement | null>): number {
  const [columns, setColumns] = React.useState(PACE_FALLBACK_COLUMNS);
  React.useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => {
      const width = element.getBoundingClientRect().width;
      if (!(width > 0)) return;
      setColumns(Math.round(Math.min(PACE_MAX_COLUMNS, Math.max(PACE_MIN_COLUMNS, width))));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return columns;
}
