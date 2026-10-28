/**
 * 注入网页的媒体同步脚本。
 *
 * Electron 的 setAudioMuted 只管整个 WebContents 的最终输出；站点自己的 <video muted>、
 * volume=0，以及我们收起前台视图时主动 pause() 的状态都不归它管。两层必须分开处理。
 * 标记只写在「由 Mosael 暂停」的元素上，恢复时不会擅自播放用户原本就暂停的视频。
 */
export function panelMediaScript(audible: boolean): string {
  return `(() => {
    const audible = ${audible ? "true" : "false"};
    document.querySelectorAll('video,audio').forEach((node) => {
      const media = node;
      try {
        if (!audible) {
          if (!media.paused) media.dataset.mosaelPausedByHost = '1';
          media.pause();
          return;
        }
        media.muted = false;
        media.defaultMuted = false;
        media.removeAttribute('muted');
        if (media.volume === 0) media.volume = 1;
        if (media.dataset.mosaelPausedByHost === '1') {
          delete media.dataset.mosaelPausedByHost;
          void media.play().catch(() => undefined);
        }
      } catch (_) {}
    });
  })()`;
}
