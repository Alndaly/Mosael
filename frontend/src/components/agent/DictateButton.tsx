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
import { Loader2, Mic, Square } from "lucide-react";
import { toast } from "sonner";

import { API_BASE, getAuthToken } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** 和后端 DICTATION_MAX_SECONDS 对齐。到点自己收,不指望被拒。 */
export const DICTATION_MAX_SECONDS = 120;

type State = "idle" | "recording" | "transcribing";

export function DictateButton({ onText, disabled }: { onText: (text: string) => void; disabled?: boolean }) {
  const t = useI18n();
  const [state, setState] = React.useState<State>("idle");
  const [seconds, setSeconds] = React.useState(0);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const stopTimerRef = React.useRef<number | null>(null);

  const cleanup = React.useCallback(() => {
    if (stopTimerRef.current !== null) {
      window.clearInterval(stopTimerRef.current);
      stopTimerRef.current = null;
    }
    // 录完要把轨道关掉,否则系统的录音指示灯一直亮着 —— 用户会以为我们在偷听。
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    recorderRef.current = null;
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
        const body = new FormData();
        body.append("clip", clip, "clip.webm");
        const token = getAuthToken();
        const response = await fetch(`${API_BASE}/api/asr/dictate`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          body,
        });
        const payload = (await response.json().catch(() => null)) as { text?: string; detail?: string } | null;
        if (!response.ok) {
          // 后端把"缺运行环境""说太长了"这类原因写在 detail 里,原样转给用户 ——
          // 换成一句"识别失败"等于把他唯一能据以行动的信息扔掉。
          toast.error(payload?.detail || t("dictateFailed"));
          return;
        }
        const text = (payload?.text ?? "").trim();
        if (!text) {
          toast.error(t("dictateHeardNothing"));
          return;
        }
        onText(text);
      } catch {
        toast.error(t("dictateFailed"));
      } finally {
        setState("idle");
      }
    };
    recorderRef.current = recorder;
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
  return (
    <Button
      variant="ghost"
      size={recording ? "sm" : "icon"}
      className={cn("rounded-full", recording && "gap-1.5 px-2.5 text-destructive")}
      aria-label={recording ? t("dictateStop") : t("dictate")}
      title={recording ? t("dictateStop") : t("dictate")}
      disabled={disabled || busy}
      onClick={() => (recording ? stop() : void start())}
    >
      {busy ? (
        <Loader2 size={15} className="animate-mosael-spin" />
      ) : recording ? (
        <>
          <Square size={11} className="fill-current" />
          {/* 计时是"还能说多久"的唯一线索 —— 到点会自动收,不说的话那一下看着像卡了。 */}
          <span className="text-ui-xs tabular-nums">{seconds}s</span>
        </>
      ) : (
        <Mic size={15} />
      )}
    </Button>
  );
}
