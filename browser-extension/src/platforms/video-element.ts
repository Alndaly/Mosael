type VideoCandidate = {
  currentSrc: string;
  src: string;
  duration: number;
  readyState: number;
  paused: boolean;
  getBoundingClientRect(): { width: number; height: number };
};

function videoScore(video: VideoCandidate): number {
  const rect = video.getBoundingClientRect();
  const visibleArea = Math.max(0, rect.width) * Math.max(0, rect.height);
  return Math.min(visibleArea * 4, 2_000_000)
    + (video.currentSrc || video.src ? 1_000_000 : 0)
    + Math.max(0, Math.min(video.readyState, 4)) * 250_000
    + (Number.isFinite(video.duration) && video.duration > 0 ? 250_000 : 0)
    + (!video.paused ? 500_000 : 0);
}

export function selectPrimaryVideo<T extends VideoCandidate>(videos: Iterable<T>): T | null {
  let selected: T | null = null;
  let selectedScore = Number.NEGATIVE_INFINITY;
  for (const video of videos) {
    const score = videoScore(video);
    if (score > selectedScore) {
      selected = video;
      selectedScore = score;
    }
  }
  return selected;
}
