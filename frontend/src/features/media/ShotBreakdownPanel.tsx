import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookPlus, Clapperboard, Copy, Check, ImageOff, Loader2, MessageSquareText } from "lucide-react";
import { toast } from "sonner";

import {
  describeOf,
  getShotBreakdown,
  getShotMotionTrack,
  hintsOf,
  listJobs,
  shotFrameUrl,
  shotsOf,
  startShotBreakdown,
  SHOT_JOB_KIND,
  type Asset,
  type NoteSource,
  type Shot,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { shotKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { MenuItem } from "@/components/ui/menu";
import { Skeleton } from "@/components/ui/skeleton";
import { jobSettled } from "@/components/jobs/runStatus";
import { SaveToNote } from "@/features/notes/SaveToNote";
import { Hint } from "@/components/ui/tooltip";
import { formatTimecode } from "@/lib/time";
import { ShotPaceStrip } from "@/features/media/ShotPaceStrip";
import { shotHintText, storyboardText, vocabKey, type ShotField } from "@/features/media/shotVocab";

/**
 * 素材详情(视频)右栏的「镜头」(ADR 0061 §5)。
 *
 * 四块,对应四种**互不相同**的状态:
 *
 * - **没拆过**(`status: "none"`,不是 404):一颗「拆镜头」+ 一句它要做什么、花多久、花不花钱;
 * - **在做**:那颗按钮换成一行进行中(进度在任务中心),底下老的那一列照旧能看;
 * - **拆过了**:一列镜头 —— 缩略图、`S03 00:12.4 · 2.6s`、景别 / 运镜的中文、画面描述、台词;
 *   点一行让左栏的播放器跳到那一镜(不另造播放器);底下「复制分镜提示词」「存成笔记」;
 * - **有表但一镜都没判过**(没有视觉模型,或判的时候调用失败):逐镜的判断字段**一个都不在**,
 *   那就只给机器量的那一半(镜号、时间、动静、台词),并说清为什么 —— 不拿空值硬画一个「无景别」。
 *
 * 对账和节奏的提示(`hints`)在列表底下逐条给人看:它们是「模型这一处判得可疑」的账,
 * 闷着就等于没记。
 *
 * 列表**上面**还有一条**节奏条**(`ShotPaceStrip`):整条动静曲线 + 刀口 + 当前镜高亮,点一下就跳到
 * 那一镜(和点一行走同一个 `onSeek`)。它自己取整条曲线(曲线有一万多个数,不在镜头表那份响应里),
 * 没拆过时不问;`none` / `missing` 各有一句人话(见那个文件)。
 */
export function ShotBreakdownPanel({ asset, onSeek, playhead = 0 }: {
  asset: Asset;
  /** 点某一镜:把这一镜的 `start` 报上去,由详情把它交给左栏那个播放器。 */
  onSeek: (seconds: number) => void;
  /** 播放器现在在第几秒 —— 节奏条据此高亮当前镜(详情从 `MediaPreviewPlayer` 的 timeupdate 报上来)。 */
  playhead?: number;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [copied, setCopied] = React.useState(false);
  //: 刚排上的那条任务:任务列表还没回来之前先把它当成「在做」,免得按钮闪一下又变回去。
  const [started, setStarted] = React.useState<{ job: JobRow; at: number } | null>(null);

  //: 还在跑的拆镜头任务(这条视频的)。关掉弹窗再打开也算数 —— 状态不在组件里。
  const jobs = useQuery({
    queryKey: shotKeys.pending(asset.workspace_id),
    queryFn: () => listJobs(asset.workspace_id, { kind: SHOT_JOB_KIND }),
    refetchInterval: (query) => (runningIn(query.state.data, asset.id) ? 1500 : false),
  });
  const running = runningIn(jobs.data, asset.id);
  const echoed = started && jobs.dataUpdatedAt <= started.at ? started.job : null;
  const activeJob = running ?? echoed;

  const breakdown = useQuery({
    queryKey: shotKeys.detail(asset.id),
    queryFn: () => getShotBreakdown(asset.id),
    //: 有任务在跑时自己也问一遍:任务中心观察到它结束才刷缓存,这一块等不了那么久。
    refetchInterval: activeJob ? 2000 : false,
  });

  const start = useMutation({
    mutationFn: () => startShotBreakdown(asset.id),
    onSuccess: (job) => {
      setStarted({ job, at: Date.now() });
      void qc.invalidateQueries({ queryKey: shotKeys.pending(asset.workspace_id) });
    },
    onError: (error) => toast.error(errorText(error)),
  });

  const data = breakdown.data;
  const shots = data ? shotsOf(data) : [];
  const hints = data ? hintsOf(data) : [];
  const describe = data ? describeOf(data) : {};
  const made = data ? storyboardText(data) : "";
  //: `status: "none"`(没拆过)时后端一镜都不给,所以「有没有表」看这一列空不空。
  const hasShots = shots.length > 0;
  //: 「判过画面没有」看**键在不在**,不看值:没判时这些键一个都没有,不是空串。
  const judged = shots.some((shot) => shot.size !== undefined || shot.camera !== undefined || shot.frame !== undefined);

  /**
   * 整条动静曲线(节奏条)。**没拆过时不问** —— 那时连刀口都没有,条画不出来;有镜头表才取。
   * 它挂在 `assets` 前缀下(`shotKeys.track`),重拆做完时和镜头表一起刷。
   */
  const track = useQuery({
    queryKey: shotKeys.track(asset.id),
    queryFn: () => getShotMotionTrack(asset.id),
    enabled: hasShots,
  });
  //: 横轴满格(秒):曲线自己的时长最准,退到末镜的结束,再退到素材的时长。
  const trackDuration = Number(track.data?.duration) || 0;
  const span = trackDuration > 0
    ? trackDuration
    : shots.reduce((high, shot) => Math.max(high, Number(shot.end) || 0), Number(asset.media_info?.duration) || 0);

  const copyStoryboard = () => {
    void navigator.clipboard?.writeText(made).then(() => {
      setCopied(true);
      toast.success(t("shotStoryboardCopied"));
      window.setTimeout(() => setCopied(false), 1500);
    });
  };

  const sources: NoteSource[] = [{ kind: "asset", id: asset.id, label: asset.name, quote: "" }];
  const noteVariants = [
    data?.report_markdown?.trim() ? { id: "report", label: t("shotNoteReport"), markdown: data.report_markdown, sources } : null,
    made ? { id: "storyboard", label: t("shotNoteStoryboard"), markdown: made, sources } : null,
  ].filter((one): one is { id: string; label: string; markdown: string; sources: NoteSource[] } => one !== null);

  return (
    <section data-shot-breakdown="" className="grid gap-2 border-t border-divider pt-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-ui-xs font-medium text-muted-foreground">{t("shotPanelTitle")}</h3>
        {hasShots && <span className="text-ui-2xs tabular-nums text-muted-foreground">{t("shotCount").replace("{n}", String(shots.length))}</span>}
      </div>

      {activeJob ? (
        <p role="status" className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
          <Loader2 size={12} className="animate-mosael-spin motion-reduce:animate-none" aria-hidden />
          {activeJob.message?.trim() || t("shotBreakdownRunning")}
        </p>
      ) : (
        <Button size="xs" variant="outline" className="w-fit" loading={start.isPending} onClick={() => start.mutate()}>
          <Clapperboard />
          {hasShots ? t("shotBreakdownRedo") : t("shotBreakdownStart")}
        </Button>
      )}

      {/* 它会花多久、花不花钱(有视觉模型时逐批判画面);重拆时补一句会覆盖。 */}
      <p className="text-ui-2xs leading-4 text-muted-foreground">{t("shotBreakdownHint")}</p>
      {hasShots && <p className="text-ui-2xs leading-4 text-muted-foreground">{t("shotBreakdownOverwrite")}</p>}

      {breakdown.isPending && (
        <div className="grid gap-1.5" aria-hidden>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {breakdown.isError && <p className="text-ui-xs text-muted-foreground">{errorText(breakdown.error)}</p>}

      {data && !hasShots && <p className="text-ui-xs text-muted-foreground">{t("shotBreakdownNone")}</p>}

      {/* 节奏条:整条动静曲线 + 刀口 + 当前镜高亮,点一下就跳到那一镜(和下面那列走同一个 onSeek)。 */}
      {hasShots && (
        <ShotPaceStrip
          shots={shots}
          track={track.data}
          duration={span}
          playhead={playhead}
          loading={track.isPending}
          error={track.isError ? errorText(track.error) : ""}
          onSeek={onSeek}
          onRebuild={activeJob ? undefined : () => start.mutate()}
        />
      )}

      {hasShots && (
        <div className="grid gap-0.5">
          {shots.map((shot) => (
            <ShotRow key={shot.id} shot={shot} assetId={asset.id} onSeek={onSeek} />
          ))}
        </div>
      )}

      {/* 判过画面才有下半截。一镜都没判过时说清为什么(`describe.error` 是后端翻好的一句人话)。 */}
      {hasShots && !judged && (
        <div className="grid gap-0.5">
          <p className="text-ui-2xs leading-4 text-muted-foreground">{t("shotNotJudged")}</p>
          {describe.error ? <p className="text-ui-2xs leading-4 text-muted-foreground">{describe.error}</p> : null}
        </div>
      )}

      {hints.length > 0 && (
        <div className="grid gap-1">
          <span className="text-ui-2xs font-medium text-muted-foreground">{t("shotHintsTitle").replace("{n}", String(hints.length))}</span>
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {hints.map((hint, index) => (
              <li key={`${hint.kind}-${hint.shot}-${index}`} data-shot-hint="" className="text-ui-2xs leading-4 text-muted-foreground">
                {shotHintText(t, hint)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasShots && (
        <div className="flex flex-wrap items-center gap-1 pt-1">
          <Button size="xs" variant="outline" disabled={!made} onClick={copyStoryboard}>
            {copied ? <Check /> : <Copy />}
            {t("shotCopyStoryboard")}
          </Button>
          <SaveToNote
            workspaceId={asset.workspace_id}
            variants={noteVariants}
            label={t("shotSaveAsNote")}
            trigger={({ open, disabled, label }) => (
              <Button size="xs" variant="outline" disabled={disabled} onClick={open}>
                <BookPlus />
                {label}
              </Button>
            )}
          />
        </div>
      )}
    </section>
  );
}

/** 任务列表里的一行(`JobSummary` / `Job` 都满足)—— 只需要这几格。 */
type JobRow = { id: string; status: string; message?: string; payload?: Record<string, unknown> };

/** 这条视频还在拆的那条任务;没有就是 null。列表里既有还在跑的,也有最近跑完的。 */
function runningIn(rows: JobRow[] | undefined, assetId: string): JobRow | null {
  return (rows ?? []).find((row) => row.payload?.asset_id === assetId && !jobSettled(row.status)) ?? null;
}

/**
 * 一镜一行。整行点一下 = 让播放器跳到这一镜的开头。
 *
 * 行本身走 `MenuItem`(列表行和菜单行同一种样子、同一个键盘走法,见 `SaveToNote` 的挑选列表),
 * 不另搓一个 `<button>`:它自带悬停底色、焦点圈和 role。
 */
/**
 * 镜头表里的那一小格插图。
 *
 * **读不出来要有兜底**:这一帧是后端按镜头位置截的,素材被清理、重拆过、或那一镜刚好没截到,
 * 接口就 404 —— 此前直接是一个 `<img>`,界面上就是浏览器的破图图标(维护者 2026-10-23 截图)。
 * 现在失败时画一枚中性图标,并给一句说明(悬停可看),和素材库里"文件缺失"的处理同一种态度:
 * 事实说不出来就明说,不装成一张图。
 */
function ShotFrameThumb({ assetId, name }: { assetId: string; name: string }) {
  const t = useI18n();
  const [broken, setBroken] = React.useState(false);
  if (broken) {
    return (
      <Hint label={t("shotFrameMissing")}>
        <span
          data-shot-frame-missing=""
          className="grid aspect-video w-16 place-items-center rounded-sm bg-workspace-subtle text-muted-foreground"
        >
          <ImageOff size={14} aria-hidden />
        </span>
      </Hint>
    );
  }
  return (
    <img
      src={shotFrameUrl(assetId, name)}
      alt=""
      loading="lazy"
      className="aspect-video w-16 rounded-sm bg-workspace-subtle object-cover"
      onError={() => setBroken(true)}
    />
  );
}

function ShotRow({ shot, assetId, onSeek }: { shot: Shot; assetId: string; onSeek: (seconds: number) => void }) {
  const t = useI18n();
  //: 表里的值是后端给的裸 dict —— 缺一格不该让整块崩掉(不该缺,但账算在这里,不算在渲染里)。
  const start = Number(shot.start) || 0;
  const seconds = Number(shot.seconds) || 0;
  const label = (field: ShotField, value: string) => {
    const key = vocabKey(field, value);
    return key ? t(key) : value;
  };
  //: 判过的字段一个都不在时,这一行只有机器量的那一半 —— 不补「无景别」这类空话。
  const meta = [
    shot.size ? label("size", shot.size) : "",
    ...(shot.camera ?? []).map((move) => label("camera", move)),
    //: 硬切是缺省,每一镜都写反而盖住真正换了转场的那几镜。
    shot.transition_in && shot.transition_in !== "cut" ? label("transition_in", shot.transition_in) : "",
    shot.rhythm ? label("rhythm", shot.rhythm) : "",
  ].filter(Boolean);

  return (
    <MenuItem
      role="button"
      data-shot-row=""
      className="items-start gap-2 px-1.5 py-1.5"
      onClick={() => onSeek(start)}
      label={
        <span className="grid grid-cols-[64px_minmax(0,1fr)] items-start gap-2">
          {/* 这一镜 15% 处的那一帧:表里的插图,和镜头表一起生成、一起没。 */}
          <ShotFrameThumb assetId={assetId} name={`${shot.id}a.jpg`} />
          <span className="grid min-w-0 gap-0.5">
            <span className="flex min-w-0 items-baseline gap-1.5">
              <span className="font-mono text-ui-xs font-medium tabular-nums text-foreground">{shot.id}</span>
              <span className="font-mono text-ui-2xs tabular-nums text-muted-foreground">
                {formatTimecode(start)} · {seconds.toFixed(1)}s
              </span>
            </span>
            {meta.length > 0 && <span className="text-ui-2xs leading-4 text-muted-foreground">{meta.join(" · ")}</span>}
            {shot.frame ? <span className="text-ui-xs leading-4 text-foreground">{shot.frame}</span> : null}
            {shot.dialogue ? (
              <span className="flex min-w-0 items-start gap-1 text-ui-2xs leading-4 text-muted-foreground">
                <MessageSquareText aria-hidden className="mt-0.5 shrink-0" />
                {shot.dialogue}
              </span>
            ) : null}
          </span>
        </span>
      }
    />
  );
}
