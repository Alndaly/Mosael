import { LoopVideo } from "@/components/loop-video";
import { darkTwin, hasImage, mediaVersion } from "@/lib/media";

/**
 * 文档正文里的「操作演示」:静音、自动循环的 MP4(见 {@link LoopVideo}),封面是同一场景的截图。
 *
 * 深色版按 `dark/` 下的同名文件找,和 {@link Shot}、{@link Recording} 同一套:用 CSS 在两段之间切,
 * 主题在服务端就定了,不会先闪一下另一套。
 */
export function Loop({ src, poster, alt }: { src: string; poster: string; alt: string }) {
  const dark = darkTwin(src);
  const hasDark = hasImage(dark);
  const versioned = (path: string) => `${path}?v=${mediaVersion(path)}`;
  return (
    <figure className="my-7">
      <LoopVideo
        src={versioned(src)}
        poster={versioned(poster)}
        label={alt}
        className={hasDark ? "dark:hidden" : undefined}
      />
      {hasDark && (
        <LoopVideo
          src={versioned(dark)}
          poster={versioned(hasImage(darkTwin(poster)) ? darkTwin(poster) : poster)}
          label={alt}
          className="hidden dark:block"
        />
      )}
    </figure>
  );
}
