import React from "react";
import { useQuery } from "@tanstack/react-query";

import { assetFilmstripUrl, fetchWaveform } from "@/api/client";
import { cn } from "@/lib/utils";

/**
 * 剪辑用的那条轨:**看着片子本身去剪**,而不是填两个秒数。
 *
 * 填数字这件事的问题不在麻烦,在于**你不知道第 3.2 秒是什么**。要么反复播放去数,要么剪
 * 出来再看一眼、不对再剪一次。一条能看见内容的轨把这一步变成"拖到这儿"。
 *
 * 视频用帧条(整条片子均匀取的几帧,后端拼成一张长图);音频没有画面,用波形 —— 人声和静音
 * 在波形上一眼分得出来,而这正是剪音频时唯一要找的东西。
 *
 * 两个把手都用**指针捕获**:轨只有几十像素高,拖着拖着划出去是常态,不捕获的话手就断了。
 */
export function TrimTrack({
  assetId,
  kind,
  duration,
  start,
  end,
  onChange,
}: {
  assetId: string;
  kind: "video" | "audio";
  /** 素材总时长(秒)。没有它就没有"拖到哪儿是第几秒"这回事,所以拿不到就不画这条轨。 */
  duration: number;
  start: number;
  end: number;
  onChange: (range: { start: number; end: number }) => void;
}) {
  const box = React.useRef<HTMLDivElement | null>(null);
  //: 正在拖哪一头。null = 没在拖。
  const [grabbing, setGrabbing] = React.useState<"start" | "end" | null>(null);

  const waveform = useQuery({
    queryKey: ["waveform", assetId],
    queryFn: () => fetchWaveform(assetId),
    enabled: kind === "audio",
    //: 峰值算完就不变了 —— 每次打开面板重取一遍纯属浪费。
    staleTime: Infinity,
  });

  const at = (clientX: number): number => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return 0;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(ratio * duration * 10) / 10;
  };

  const move = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!grabbing) return;
    const value = at(event.clientX);
    //: 两头**不许越过对方**。越过之后剪出来是空的,而用户拖的时候看不出这一点。
    if (grabbing === "start") onChange({ start: Math.min(value, end - 0.1), end });
    else onChange({ start, end: Math.max(value, start + 0.1) });
  };

  const left = duration > 0 ? (start / duration) * 100 : 0;
  const right = duration > 0 ? (end / duration) * 100 : 100;

  return (
    <div
      ref={box}
      //: nodrag/nopan:这东西活在画布上,不挂的话拖把手会变成拖画布。
      className="nodrag nopan relative h-12 w-full select-none overflow-hidden rounded-md border border-border bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)]"
      onPointerMove={move}
      onPointerUp={(event) => {
        event.currentTarget.releasePointerCapture(event.pointerId);
        setGrabbing(null);
      }}
    >
      {kind === "video" ? (
        //: 帧条铺满整条轨。**不保持比例** —— 这里要的是"第几秒长什么样",而不是每一格都方正。
        <img
          src={assetFilmstripUrl(assetId)}
          alt=""
          draggable={false}
          className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-90"
        />
      ) : (
        <Waveform peaks={waveform.data?.peaks ?? []} />
      )}

      {/* 选区之外压暗 —— 剪掉的那两头要一眼看出来。 */}
      <div className="pointer-events-none absolute inset-y-0 left-0 bg-background/70" style={{ width: `${left}%` }} />
      <div className="pointer-events-none absolute inset-y-0 right-0 bg-background/70" style={{ width: `${100 - right}%` }} />
      <div
        className="pointer-events-none absolute inset-y-0 border-y-2 border-primary"
        style={{ left: `${left}%`, width: `${right - left}%` }}
      />

      {(["start", "end"] as const).map((side) => (
        <div
          key={side}
          onPointerDown={(event) => {
            event.currentTarget.parentElement?.setPointerCapture(event.pointerId);
            setGrabbing(side);
          }}
          //: 把手比看上去宽:-mx 让它的可抓区域探出可见的那道竖条,细条本身很难按准。
          className={cn(
            "absolute inset-y-0 z-10 flex w-3 cursor-ew-resize items-center justify-center",
            grabbing === side && "z-20",
          )}
          style={{ left: `calc(${side === "start" ? left : right}% - 6px)` }}
        >
          <span className="h-full w-1 rounded-full bg-primary shadow-sm" />
        </div>
      ))}
    </div>
  );
}

/** 波形:峰值桶画成一排竖条。**不追求好看** —— 它要回答的只有「哪一段有人在说话」。 */
function Waveform({ peaks }: { peaks: number[] }) {
  if (peaks.length === 0) return null;
  //: 桶有一千个,而轨只有几百像素宽 —— 抽稀到 120 根,再多也是糊成一片。
  const step = Math.max(1, Math.floor(peaks.length / 120));
  const bars = peaks.filter((_, index) => index % step === 0);
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center gap-px px-px">
      {bars.map((peak, index) => (
        <span
          key={index}
          className="flex-1 rounded-full bg-muted-foreground/60"
          style={{ height: `${Math.max(6, peak * 100)}%` }}
        />
      ))}
    </div>
  );
}
