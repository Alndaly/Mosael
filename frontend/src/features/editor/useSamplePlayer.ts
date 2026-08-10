import React from "react";

/**
 * 试听一段音频:**按下去能收回来**,而且看得出在放哪一个。
 *
 * 此前音色库那个 ▷ 只调 `audio.play()` —— 按下去开始放,再按还是从头放,没有任何办法停;
 * 切走页面它还在响(那个 `Audio` 对象没人负责关)。一个按下去没法收回的按钮,和一个不显示
 * 当前状态的按钮,是同一个毛病的两面。
 *
 * 同一时刻只放一个:换一个就把前一个停掉,而不是两段人声叠在一起。
 */
export function useSamplePlayer(srcFor: (id: string) => string) {
  const [playingId, setPlayingId] = React.useState<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const ensure = React.useCallback(() => {
    if (!audioRef.current) {
      const audio = new Audio();
      // 放完、以及任何原因暂停(包括系统媒体键),都把状态放回去 —— 否则按钮会一直
      // 停在"正在放",而声音早就没了。
      audio.onended = () => setPlayingId(null);
      audio.onpause = () => setPlayingId(null);
      audioRef.current = audio;
    }
    return audioRef.current;
  }, []);

  const stop = React.useCallback(() => {
    audioRef.current?.pause();
    setPlayingId(null);
  }, []);

  const toggle = React.useCallback(
    (id: string) => {
      const audio = ensure();
      if (playingId === id) {
        stop();
        return;
      }
      if (playingId) audio.pause(); // 换一个之前先把上一个停掉;本来就没在放就别多此一举
      audio.src = srcFor(id);
      audio.currentTime = 0; // 同一个再放一次要从头开始
      setPlayingId(id);
      void audio.play().catch(() => setPlayingId(null));
    },
    [ensure, playingId, srcFor, stop],
  );

  // 卸载时闭嘴。切走页面声音还在响,是没人负责的那种 bug。
  React.useEffect(() => () => audioRef.current?.pause(), []);

  return { playingId, toggle, stop, _audio: () => audioRef.current };
}
