/**
 * 浮标里那颗会动的核心:五根随真实音量起伏的条,外加一圈表达"轮到谁"的动效。
 *
 * **为什么是真音量而不是一段循环动画。** 免提最让人不安的一句话是"我说了,它到底听没听
 * 见"——一段无论如何都在跳的假动画回答不了这个问题,它在麦克风被系统静音时跳得一样欢。
 * 这几根条读的是检测器同一路 RMS,而且**以"开口阈值"为 1.0 归一化**:它们越过一半高度
 * 变成主色的那一刻,正是检测器判定你开始说话的那一刻。于是"要多大声"这件事不用猜。
 *
 * **为什么用 rAF 直接写 DOM,而不是 setState。** 采样 20 次/秒,画面要 60 帧才不顿。走
 * state 的话浮标(连同它挂着的两个轮询查询)每秒重渲染二十次,而这个数只有五根条在看。
 *
 * 减少动效偏好:呼吸和涟漪是 CSS 动画,被 tokens.css 里那条全局规则统一压掉。条形保留 ——
 * 它是**反馈**不是装饰,压掉之后就没有任何东西能说明"它听见了"。
 */

import React from "react";
import { Loader2 } from "lucide-react";

import type { VoiceLoopState } from "@/components/agent/useVoiceLoop";
import { cn } from "@/lib/utils";

/** 五根条各自的权重。**不给同一个高度** —— 五根一起上下的东西看着像进度条,
 *  像波形才读得出"这是声音"。中间高、两边低,和人对声波的既有印象一致。 */
const WEIGHTS = [0.45, 0.78, 1, 0.78, 0.45];
/** 条的最矮和最高(px)。最矮不是 0:全静音时五个点还在,说明它还醒着。 */
const MIN_H = 3;
const MAX_H = 17;

export function VoiceOrb({
  state,
  levelRef,
}: {
  state: VoiceLoopState;
  /** 当前音量,1.0 = 开口阈值。见 useVoiceLoop。 */
  levelRef: React.MutableRefObject<number>;
}) {
  const bars = React.useRef<(HTMLSpanElement | null)[]>([]);
  const stateRef = React.useRef(state);
  stateRef.current = state;

  React.useEffect(() => {
    if (state === "off" || state === "thinking") return;
    let frame = 0;
    //: 平滑值。直接画原始 RMS 会抖得像噪点 —— 上升跟得快(开口要立刻有反应),
    //: 下降慢一点(每个字之间的换气不该让它归零闪一下)。
    let smoothed = 0;
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      const speaking = stateRef.current === "speaking";
      //: 它在念的时候,麦克风收到的是**它自己的声音**——拿来驱动等于把回声画成"你在说话"。
      //: 所以这一段走一条合成的行波:表达的是"现在轮到它",不冒充测量。
      const raw = speaking ? 0.55 + 0.45 * Math.sin(now / 140) : levelRef.current;
      smoothed += (raw - smoothed) * (raw > smoothed ? 0.45 : 0.12);
      const over = !speaking && smoothed >= 1;
      for (const [index, bar] of bars.current.entries()) {
        if (!bar) continue;
        //: 行波:每根条相位错开,于是是"一道声音扫过去"而不是五根一起呼吸。
        const phase = speaking ? 0.7 + 0.3 * Math.sin(now / 140 - index * 0.9) : 1;
        const height = MIN_H + Math.min(smoothed, 2) * 0.5 * (MAX_H - MIN_H) * WEIGHTS[index] * phase;
        bar.style.height = `${Math.min(height, MAX_H)}px`;
        //: 越过阈值就换色。**这是这个组件里信息量最大的一像素** —— 它说的是
        //: "这一句算数了",而不只是"有声音"。
        bar.style.opacity = over || speaking ? "1" : "0.55";
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [state, levelRef]);

  if (state === "thinking") return <Loader2 size={20} className="animate-mosael-spin text-primary" />;

  return (
    <span className="pointer-events-none relative grid size-full place-items-center">
      {/* 在等你开口:慢呼吸。它不响应声音 —— 响应声音的是里面那几根条。 */}
      {state === "listening" && (
        <span className="animate-voice-breathe absolute inset-[3px] rounded-full border border-primary/50" />
      )}
      {/* 它在念:涟漪往外走。方向本身就是"声音从这儿出去"。 */}
      {state === "speaking" && (
        <span className="animate-voice-ripple absolute inset-0 rounded-full border border-foreground/40" />
      )}
      <span className="flex h-[18px] items-center gap-[3px]">
        {WEIGHTS.map((_, index) => (
          <span
            key={index}
            ref={(node) => {
              bars.current[index] = node;
            }}
            className={cn(
              "w-[2.5px] rounded-full transition-colors",
              state === "off" && "bg-muted-foreground",
              state === "listening" && "bg-primary/70",
              state === "hearing" && "bg-primary",
              state === "speaking" && "bg-foreground",
            )}
            style={{ height: MIN_H }}
          />
        ))}
      </span>
    </span>
  );
}
