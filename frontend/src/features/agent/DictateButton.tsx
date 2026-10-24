/**
 * 对着输入框说话,说完把文字填进去。
 *
 * **一份实现,两个入口共用**(工作区助手与 AI 工作台)—— 工具行上每多一个各写各的按钮,
 * 位置、顺序、有无就多一次不一致,这一行已经为此收敛过一次。
 *
 * 几个刻意的选择:
 *
 * · **点一下开始、再点一下结束**,不是按住说话。输入框是"想到哪说到哪"的地方,按住不放
 *   会逼人先想好整句;而且鼠标一旦移出按钮,按住的手势就断了。
 * · **追加,不覆盖**。用户完全可能先打了半句再改用说的,把输入框清掉等于吃掉他打的字。
 * · **到点自动停**。后端的上限是 120 秒(DICTATION_MAX_SECONDS),让它录到 121 秒再被拒,
 *   等于把那 121 秒白扔了 —— 到点就收,把已经说的那段交上去。
 * · **失败要出声**。识别不出来、没装运行环境、没给麦克风权限,都得说人话,而不是一个
 *   点了没反应的按钮。
 */

import React from "react";
import { Mic, Square } from "lucide-react";
import { toast } from "sonner";

import { ApiError, dictate } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { useMicLevel } from "@/features/agent/useMicLevel";
import { cn } from "@/lib/utils";

/** 和后端 DICTATION_MAX_SECONDS 对齐。到点自己收,不指望被拒。 */
export const DICTATION_MAX_SECONDS = 120;

type State = "idle" | "recording" | "transcribing";

export function DictateButton({ onText, disabled }: { onText: (text: string) => void; disabled?: boolean }) {
  const t = useI18n();
  const [state, setState] = React.useState<State>("idle");
  const [seconds, setSeconds] = React.useState(0);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  //: 电平要在**渲染时**读:只留 ref 的话它变了也不会重画。
  const [stream, setStream] = React.useState<MediaStream | null>(null);
  const stopTimerRef = React.useRef<number | null>(null);

  const cleanup = React.useCallback(() => {
    if (stopTimerRef.current !== null) {
      window.clearInterval(stopTimerRef.current);
      stopTimerRef.current = null;
    }
    // 录完要把轨道关掉,否则系统的录音指示灯一直亮着 —— 用户会以为我们在偷听。
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    recorderRef.current = null;
    setStream(null);
  }, []);

  React.useEffect(() => cleanup, [cleanup]);

  async function start() {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      // 拒绝授权和没有麦克风在这里长得一样,而用户能做的事也一样:去系统设置里看一眼。
      toast.error(t("dictateNoMic"));
      return;
    }
    const recorder = new MediaRecorder(stream);
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (event) => event.data.size > 0 && chunks.push(event.data);
    recorder.onstop = async () => {
      cleanup();
      const clip = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      if (clip.size === 0) {
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const text = ((await dictate(clip)).text ?? "").trim();
        if (!text) {
          toast.error(t("dictateHeardNothing"));
          return;
        }
        onText(text);
      } catch (error) {
        // 后端把"缺运行环境""说太长了"这类原因写在 detail 里,原样转给用户 ——
        // 换成一句"识别失败"等于把他唯一能据以行动的信息扔掉。
        toast.error(error instanceof ApiError ? error.message : t("dictateFailed"));
      } finally {
        setState("idle");
      }
    };
    recorderRef.current = recorder;
    setStream(stream);
    recorder.start();
    setSeconds(0);
    setState("recording");
    stopTimerRef.current = window.setInterval(() => {
      setSeconds((current) => {
        const next = current + 1;
        if (next >= DICTATION_MAX_SECONDS) recorderRef.current?.stop();
        return next;
      });
    }, 1000);
  }

  function stop() {
    recorderRef.current?.stop();
  }

  const busy = state === "transcribing";
  const recording = state === "recording";
  //: 录音时给一条实时电平:看不到自己有没有出声,是"录完才发现识别不出来"的根源。
  const level = useMicLevel(recording ? stream : null);
  const levelPercent = Math.round(level * 100);
  //: 转写时那颗按钮只剩一圈转(Button 的 loading),名字还写着「说话输入」的话,悬停得到的
  //: 是一句已经做完的事。用编辑器转写那条既有文案 —— 它此刻确实在转写。
  const label = recording ? t("dictateStop") : busy ? t("transcribing") : t("dictate");
  return (
    <IconButton
      variant="ghost"
      //: 两种形态都钉在 28px 高。**录制时会从圆变成带计时的胶囊**,高度再变的话整条
      //: 工具行会跟着跳一下 —— 而那一跳发生在你刚开口的瞬间,看着像点错了什么。
      //: 所以换的是 xs↔icon-xs 这一对(同一档的胶囊和圆),不是 sm↔icon(32↔36)。
      size={recording ? "xs" : "icon-xs"}
      className={cn(recording && "gap-1.5 text-destructive")}
      label={label}
      disabled={disabled}
      loading={busy}
      onClick={() => (recording ? stop() : void start())}
    >
      {recording ? (
        <>
          <Square size={11} className="fill-current" />
          {/* 计时是"还能说多久"的唯一线索 —— 到点会自动收,不说的话那一下看着像卡了。 */}
          <span className="text-ui-xs tabular-nums">{seconds}s</span>
          {/*: 三格电平:开口就动,静音/选错麦克风就一直是空的 —— 那正是要让人看见的事。
               宽度固定(26px),胶囊的宽度只随计时那几位数字变,不会因为电平抖动而抖。 */}
          <span
            data-dictate-level=""
            role="progressbar"
            aria-label={t("dictateLevel")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={levelPercent}
            className="flex h-3 w-4 shrink-0 items-end gap-[2px]"
          >
            {/*: 从左到右**越来越高**:这是一条电平,不是装饰性的三道杠 —— 高度顺序反过来
                 会读成"中间最响",和真实的音量没关系。 */}
            {[0.5, 0.78, 1].map((weight, index) => (
              <i
                key={index}
                aria-hidden
                className="w-[2.5px] flex-1 rounded-full bg-current"
                //: 最低留一点点高度:全 0 的三条线看起来像没画出来。
                style={{ height: `${Math.max(10, Math.min(100, levelPercent * weight * 1.5))}%` }}
              />
            ))}
          </span>
        </>
      ) : (
        <Mic size={14} />
      )}
    </IconButton>
  );
}
