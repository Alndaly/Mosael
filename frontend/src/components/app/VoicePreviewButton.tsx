import React from "react";
import { Square, Volume2 } from "lucide-react";
import { toast } from "sonner";

import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { playBlob, stopPlayback } from "@/lib/audioPlayback";

/**
 * 试听键:点一下取来念,再点一下停。同一时刻只响一段(和对话里念消息共用 lib/audioPlayback 那一个播放器)。
 *
 * 音频从哪来由调用方给(`load`)—— 各处试听的是不同的东西,取、播、停这一段是同一件事。
 * `disabledReason` 是灰着的时候 title 上那句「为什么点不了」。
 */
export function VoicePreviewButton({
  load,
  disabled = false,
  disabledReason,
}: {
  load: () => Promise<Blob>;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const t = useI18n();
  const [state, setState] = React.useState<"idle" | "loading" | "playing">("idle");
  //: 卸载之后取回来的音频不该再响 —— 人已经离开这一屏了。在 effect 里置回 true:
  //: StrictMode 下挂载会走「挂 → 卸 → 挂」,只在初值里写 true 的话第二次挂上后它永远是 false。
  const mounted = React.useRef(false);
  const playing = React.useRef(false);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // 只停自己念的那段:别处(对话里的喇叭)正在响的不归这里管。
      if (playing.current) stopPlayback();
    };
  }, []);

  const play = async () => {
    setState("loading");
    try {
      const audio = await load();
      if (!mounted.current) return;
      setState("playing");
      playing.current = true;
      await playBlob(audio);
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      playing.current = false;
      if (mounted.current) setState("idle");
    }
  };

  const label = state === "playing" ? t("voicePreviewStop") : t("voicePreview");
  return (
    <Button
      variant="outline"
      size="icon"
      loading={state === "loading"}
      disabled={disabled}
      aria-label={label}
      title={disabled ? (disabledReason ?? label) : label}
      onClick={() => (state === "playing" ? stopPlayback() : void play())}
    >
      {state === "playing" ? <Square /> : <Volume2 />}
    </Button>
  );
}
