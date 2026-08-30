import * as React from "react";
import { ExternalLink } from "lucide-react";
import { PhotoSlider } from "react-photo-view";
import "react-photo-view/dist/react-photo-view.css";

import { useI18n } from "@/app/preferences";
import { BoardVideo } from "@/features/boards/BoardPlayer";
import { cn } from "@/lib/utils";

export type ImagePreviewItem = {
  src: string;
  title?: string;
  /** 这一项是视频 —— **同一个灯箱,换一种渲染**。另开一个视频弹层的话,关闭、遮罩、
   *  Esc、层级这几件事就要各写一遍,而它们已经在这儿处理过了(包括那条「关掉之后
   *  还接管一会儿点击」的坑)。 */
  video?: boolean;
};

type ImagePreviewState = ImagePreviewItem & {
  /** 画廊:同场景的全部图片(如生成会话里所有产出)。点开的 src 决定初始位置,
   *  PhotoSlider 自带左右翻页/计数。省略 = 单张预览,老调用方不变。 */
  gallery?: ImagePreviewItem[];
};

type ImagePreviewContextValue = {
  openImagePreview: (image: ImagePreviewState) => void;
};

const ImagePreviewContext = React.createContext<ImagePreviewContextValue | null>(null);

export function ImagePreviewProvider({ children }: { children: React.ReactNode }) {
  const t = useI18n();
  const [images, setImages] = React.useState<ImagePreviewItem[]>([]);
  const [index, setIndex] = React.useState(0);
  const [visible, setVisible] = React.useState(false);
  //: 打开那一刻的视口大小 —— 视频那一项按它出盒子(见下面 width/height 那段)。
  const [viewport, setViewport] = React.useState({ width: 1280, height: 720 });

  const openImagePreview = React.useCallback((next: ImagePreviewState) => {
    setViewport({ width: window.innerWidth, height: window.innerHeight });
    //: 单张时**把这一项整个带过去**,别逐字段重建 —— 漏掉哪个字段不会报错,只会让那个
    //: 功能悄悄失效(video 标记就是这么丢的:灯箱开了,里面什么都没有)。
    const { gallery, ...single } = next;
    const list = gallery?.length ? gallery : [single];
    const at = list.findIndex((item) => item.src === next.src);
    setImages(list);
    setIndex(at >= 0 ? at : 0);
    setVisible(true);
  }, []);
  const close = React.useCallback(() => setVisible(false), []);
  const reset = React.useCallback(() => setImages([]), []);

  const value = React.useMemo<ImagePreviewContextValue>(() => ({ openImagePreview }), [openImagePreview]);

  return (
    <ImagePreviewContext.Provider value={value}>
      {children}
      <PhotoSlider
        images={images.map((item) => ({
          key: item.src,
          //: **视频那一项不给 src。** 库里 render 的优先级比 src 低(它的注释原话),给了
          //: src 就走 <img> 那条路 —— 一个视频地址当图片加载,结果是整块空白。
          src: item.video ? undefined : item.src,
          overlay: item.title ?? t("imagePreviewTitle"),
          //: 自定义渲染要**显式给尺寸**:那一层按图片的自然宽高摆位,视频这边它测不到,
          //: 不给就是 0×0(一片空白),给死一个 1920×1080 又会顶出视口。给**视口大小** ——
          //: 于是它摆出来的盒子正好铺满屏幕,播放器再按 object-contain 收进去。
          //:
          //: 不能用 position: fixed 自己铺满:这块内容住在一个带 transform 的容器里,而祖先
          //: 一旦有 transform,它就成了后代 fixed 的包含块 —— 视频会跑到屏幕角上去(实测)。
          width: item.video ? viewport.width : undefined,
          height: item.video ? viewport.height : undefined,
          //: 视频交给**自己写的**播放器,不是原生 controls —— 浏览器自带那条控件各家各的
          //: 样子、不吃主题,而画板节点上早就换掉了它,大图里又冒出来就是两套东西。
          //: 缩放/拖拽那套对视频没意义:它要的是能播、能拖进度。
          //: **不套 attrs。** 那套属性是给图片的缩放/拖拽用的(transform + 按自然宽高摆位),
          //: 对视频既没意义又会把它顶出视口。这里自己铺满视口,播放器按 object-contain 收进去;
          //: 关闭仍然走灯箱自己的 ✕ 和 Esc。
          render: item.video
            ? ({ attrs }) => (
                <div {...attrs}>
                  {/* 播放器铺满这个盒子;画面按 object-contain 收进去,不会被拉变形。 */}
                  <BoardVideo assetSrc={item.src} autoPlay className="!bg-transparent" />
                </div>
              )
            : undefined,
        }))}
        index={index}
        onIndexChange={setIndex}
        visible={visible && images.length > 0}
        onClose={close}
        afterClose={reset}
        // react-photo-view 自带样式不在 cascade layer 里,会压过 utilities layer——覆盖其内部结构一律加 `!`。
        // 关闭后这层还会在 DOM 里留一会儿(等它自己的收尾动画),期间虽然看不见却仍然接管
        // 点击 —— 表现为「关掉大图后有一小段时间画布点不动、节点拖不了」。不可见就不该拦事件。
        className={cn(
          !visible && "pointer-events-none!",
          "z-[150]! [&_.PhotoView-Slider\_\_BannerWrap]:h-12! [&_.PhotoView-Slider\_\_BannerWrap]:bg-[linear-gradient(to_bottom,rgb(0_0_0/0.42),transparent)]! [&_.PhotoView-Slider\_\_Counter]:font-mono! [&_.PhotoView-Slider\_\_Counter]:text-ui-xs! [&_.PhotoView-Slider\_\_Counter]:text-[rgb(255_255_255/0.68)]! [&_.PhotoView-Slider\_\_toolbarIcon]:h-9! [&_.PhotoView-Slider\_\_toolbarIcon]:w-9! [&_.PhotoView-Slider\_\_toolbarIcon]:text-[rgb(255_255_255/0.82)]! [&_:is(.PhotoView-Slider\_\_ArrowLeft,.PhotoView-Slider\_\_ArrowRight)]:text-[rgb(255_255_255/0.78)]!",
        )}
        maskClassName="will-change-[opacity]"
        photoClassName="rounded-lg will-change-[transform,opacity] [outline:1px_solid_rgb(255_255_255/0.12)]"
        maskOpacity={0.88}
        toolbarRender={({ images, index }) => {
          const src = images[index]?.src;
          if (!src) return null;
          return (
            <a
              href={src}
              target="_blank"
              rel="noreferrer noopener"
              className="mr-2 inline-flex min-h-[30px] items-center gap-1.5 rounded-full border border-[rgb(255_255_255/0.18)] bg-[rgb(255_255_255/0.12)] px-[11px] text-xs text-white no-underline hover:bg-[rgb(255_255_255/0.2)]"
              onClick={(event) => event.stopPropagation()}
            >
              <ExternalLink size={14} /> {t("openOriginal")}
            </a>
          );
        }}
        overlayRender={({ overlay }) =>
          overlay ? (
            <div className="fixed bottom-[22px] left-1/2 max-w-[min(760px,calc(100vw-64px))] -translate-x-1/2 truncate rounded-full border border-[rgb(255_255_255/0.14)] bg-[rgb(0_0_0/0.38)] px-[13px] py-[7px] text-ui-sm font-semibold text-white backdrop-blur-[10px]">
              {overlay}
            </div>
          ) : null
        }
      />
    </ImagePreviewContext.Provider>
  );
}

export function useImagePreview() {
  const value = React.useContext(ImagePreviewContext);
  if (!value) throw new Error("useImagePreview must be used inside ImagePreviewProvider");
  return value;
}
