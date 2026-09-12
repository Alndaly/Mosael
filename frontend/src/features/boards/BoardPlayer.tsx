import React from "react";
import { useOnViewportChange } from "@xyflow/react";
import { Play } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl } from "@/api/client";
import { AudioPlayerBar, VideoPlayer } from "@/components/app/media-playback";
import { cn } from "@/lib/utils";

/**
 * 画板上的播放器 —— 面孔与机件都在 components/app/media-playback(VideoPlayer /
 * AudioPlayerBar / usePlayback / Scrubber),智能体工具结果、素材预览、大图灯箱用的是
 * 同一副:播放手感全站只有一份,改一处处处生效。
 * 「不用原生 controls」「nodrag 只能挂在进度条上」的完整推理也在 media-playback 里。
 */

//: 提前这么多像素就挂上 —— 等真的进了视野才挂,用户会看见封面"变成"播放器闪一下。
const MOUNT_MARGIN_PX = 300;
//: 画到这么窄就不值得占一个解码器了。**这一条挡的是缩放**:缩到「适应画布」时整张画板都
//: 在视野里,只按"进没进视野"判,一百个视频会一起挂上 —— 而那时每个也就指甲盖大。
//: (实测:100 个节点缩到 0.3 倍,相交的是 100 个,够大的只有 12 个。)
const MIN_LIVE_WIDTH = 96;

/** 这块地方现在值不值得占一个解码器。传的是**视口坐标系里的矩形**,所以缩放天然算在里面。 */
export function shouldMountVideo(
  rect: { top: number; left: number; bottom: number; right: number; width: number },
  viewport: { width: number; height: number },
): boolean {
  if (rect.width < MIN_LIVE_WIDTH) return false;
  return (
    rect.right > -MOUNT_MARGIN_PX
    && rect.bottom > -MOUNT_MARGIN_PX
    && rect.left < viewport.width + MOUNT_MARGIN_PX
    && rect.top < viewport.height + MOUNT_MARGIN_PX
  );
}

/**
 * 画板上的视频节点。**离开视野就把 `<video>` 卸掉。**
 *
 * 一个 `<video>` 元素占着一个解码器,而 Chrome 每页大约只给 75 个。画板恰恰是最容易摆上
 * 一百个节点的地方,而超出上限之后,后面那些**不报错**,就是一直黑着 —— 用户会以为素材坏了。
 * 屏幕上同时看得见的从来只有十几个,剩下的没有理由占着解码器。
 *
 * 卸掉之后画的是这份素材的封面图。一张图不占解码器,而且和暂停在第一帧的播放器长得一样 ——
 * 拖动画布时不该看见节点在"有画面"和"一片黑"之间闪。
 *
 * **正在播的那个不卸**:你可能正一边听着它一边把画布拖去看别处,卸掉等于替用户按了停止。
 * 而正在播的永远只有一两个,不是这个问题的来源。暂停的位置记下来,重新挂上时接着放。
 *
 * **两个触发器,因为一个不够。** IntersectionObserver 管"进出视野",但它只在相交状态变化时
 * 才叫 —— 而 React Flow 的缩放是 transform,一个**始终**在视野里的节点,从 0.15 倍拉到 1 倍
 * 全程一次都不叫(实测过)。于是"太小就不挂"这条会一直拿着缩放前的宽度:从总览缩放回来之后,
 * 那些节点会卡在封面上再也不挂播放器。所以缩放停下时再量一遍。
 */
export function BoardVideo({
  assetId,
  className,
  onNaturalSize,
}: {
  assetId?: string;
  className?: string;
  onNaturalSize?: (width: number, height: number) => void;
}) {
  const box = React.useRef<HTMLDivElement | null>(null);
  const [live, setLive] = React.useState(false);
  const [playing, setPlaying] = React.useState(false);
  const resumeAt = React.useRef(0);
  //: 封面取不到时记下**是哪一份素材**取不到 —— 换了素材自然就不算数了,不用再写一个 effect
  //: 去清它。取不到是正常的(缩略图是尽力而为的,见 media/thumbnails 的 best-effort),
  //: 而**露出浏览器那张破损图**是这次巡检修过的另一个 bug(dda92454),不能在这儿再犯一次。
  const [brokenPoster, setBrokenPoster] = React.useState("");

  const onPlaybackChange = React.useCallback((state: { playing: boolean; at: number }) => {
    resumeAt.current = state.at;
    // 同值时 React 自己会跳过重渲染,所以每次 timeupdate 叫这一下是不要钱的。
    setPlaying(state.playing);
  }, []);

  /** 拿当下的真实矩形重新判一次。两个触发器共用它,免得两条路各有一套判据。 */
  const measure = React.useCallback((rect?: DOMRect | DOMRectReadOnly | null) => {
    const current = rect ?? box.current?.getBoundingClientRect();
    if (!current) return;
    setLive(shouldMountVideo(current, { width: window.innerWidth, height: window.innerHeight }));
  }, []);

  React.useEffect(() => {
    const element = box.current;
    // 没有观察器就一律挂上 —— 宁可占解码器,也不能让画板上的视频**根本不出现**。
    if (!element || typeof IntersectionObserver === "undefined") {
      setLive(true);
      return;
    }
    // entry 只当"有事发生"的信号,判据仍走 measure —— rootMargin 只决定它**什么时候**叫。
    const observer = new IntersectionObserver(
      ([entry]) => measure(entry.boundingClientRect),
      { rootMargin: `${MOUNT_MARGIN_PX}px` },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [measure]);

  // 缩放/平移**停下时**补一次(见上面的说明)。只挂 onEnd,不挂 onChange:后者每帧都叫,
  // 而一百个节点每帧各重判一次,为的是一件停下来再做也不迟的事。
  const onViewportEnd = React.useCallback(() => measure(), [measure]);
  useOnViewportChange({ onEnd: onViewportEnd });

  return (
    // 外层只负责占位和被观察 —— 圆角、底色这些由调用方的 className 给里面那层,
    // 两层都套一遍只会在同一处画两遍。
    <div ref={box} className="relative h-full w-full">
      {live || playing ? (
        <VideoPlayer
          assetId={assetId}
          onNaturalSize={onNaturalSize}
          startAt={resumeAt.current}
          onPlaybackChange={onPlaybackChange}
          className={className}
        />
      ) : (
        // 卸掉时的样子:封面 + 那枚播放标记。**标记不是按钮** —— 看得见它的时候
        // 真播放器早就挂上了(提前 300px),这里给一个点不动的按钮只会是个假承诺。
        <div className={cn("h-full w-full overflow-hidden bg-black", className)} data-board-video="dormant">
          {assetId && brokenPoster !== assetId && (
            //: **不开原生懒加载。** React Flow 的视口是 transform 过的,浏览器据此判断
            //: "还没进视野"而迟迟不发请求,图就一直是 0×0(画板的图片节点上踩过,
            //: 所以那里也是 lazy={false})。而封面本来就该早早取好:它是**替代**解码器的
            //: 那个便宜东西,一百张缩略图加起来也没有一个 <video> 贵。
            <img
              src={assetThumbnailUrl(assetId)}
              alt=""
              onError={() => setBrokenPoster(assetId)}
              className="h-full w-full object-contain"
            />
          )}
          <span className="absolute inset-0 grid place-items-center">
            <span className="grid h-9 w-9 place-items-center rounded-full bg-black/55 text-white backdrop-blur">
              <Play size={15} className="translate-x-px" fill="currentColor" />
            </span>
          </span>
        </div>
      )}
    </div>
  );
}

/** 画板上的音频节点 —— 这里只负责按 id 取带令牌的地址。 */
export function BoardAudio({ assetId, className }: { assetId: string; className?: string }) {
  return <AudioPlayerBar src={assetFileUrl(assetId)} className={className} />;
}
