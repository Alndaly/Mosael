import { assetFileUrl } from "@/api/client";
import { AudioPlayerBar, VideoPlayer } from "@/components/app/media-playback";

/**
 * 画板上的播放器 —— 面孔与机件都在 components/app/media-playback(VideoPlayer /
 * AudioPlayerBar / usePlayback / Scrubber),智能体工具结果、素材预览、大图灯箱用的是
 * 同一副:播放手感全站只有一份,改一处处处生效。这里只剩按画板习惯取地址的薄封装。
 * 「不用原生 controls」「nodrag 只能挂在进度条上」的完整推理也在 media-playback 里。
 */

export function BoardVideo(props: {
  assetId?: string;
  assetSrc?: string;
  autoPlay?: boolean;
  className?: string;
  onNaturalSize?: (width: number, height: number) => void;
}) {
  return <VideoPlayer {...props} />;
}

/** 画板上的音频节点 —— 这里只负责按 id 取带令牌的地址。 */
export function BoardAudio({ assetId, className }: { assetId: string; className?: string }) {
  return <AudioPlayerBar src={assetFileUrl(assetId)} className={className} />;
}
