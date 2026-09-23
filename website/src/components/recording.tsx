import { darkTwin, hasImage, mediaVersion } from "@/lib/media";
import { cn } from "@/lib/utils";

/** Real screen recordings: user-controlled playback, no autoplay or audio surprises. */
export function Recording({ src, poster, caption }: { src: string; poster: string; caption: string }) {
  const dark = darkTwin(src);
  const hasDark = hasImage(dark);
  const versioned = (path: string) => `${path}?v=${mediaVersion(path)}`;
  return (
    <figure className="my-7">
      {([false, ...(hasDark ? [true] : [])]).map((isDark) => (
        <video
          key={String(isDark)}
          controls
          // 录屏本来就没有音轨(record-doc-media.py 用 -an 截的),标出来也省得屏幕阅读器找字幕轨。
          muted
          playsInline
          preload="none"
          aria-label={caption}
          poster={versioned(isDark && hasImage(darkTwin(poster)) ? darkTwin(poster) : poster)}
          className={cn("aspect-[8/5] h-auto w-full rounded-xl bg-muted", hasDark && (isDark ? "hidden dark:block" : "dark:hidden"))}
        >
          <source src={versioned(isDark ? dark : src)} type="video/mp4" />
          <a href={src}>{caption}</a>
        </video>
      ))}
      <figcaption className="mt-3 text-sm text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}
