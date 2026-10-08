import * as React from "react";
import { ExternalLink, X } from "lucide-react";
import { PhotoSlider } from "react-photo-view";

import { useI18n } from "@/app/preferences";
import { IMAGE_PREVIEW_EVENT, type ImagePreviewRequest } from "@/components/app/image-preview-request";
import { VideoPlayer } from "@/components/app/media-playback";
import { APP_CHROME } from "@/components/ui/appChrome";
import { IconButton } from "@/components/ui/icon-button";
import { useNativeViewAside } from "@/components/ui/nativeViewAside";
import { HintRegion } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { ImagePreviewContext, type ImagePreviewContextValue, type ImagePreviewItem, type ImagePreviewState } from "@/components/app/imagePreviewContext";

//: 灯箱的 context 和取它的 hook 在 imagePreviewContext 里(只依赖 React,见 app/contextIdentity.test.ts):这个模块引着
//: 播放器、图标按钮这些界面组件,改其中任何一个都会让它被热更新重跑 —— context 要是住在这里,就换出一个新的,
//: 页面里的 useImagePreview 读到 null,整页报「must be used inside ImagePreviewProvider」(改 media-playback.tsx 时实测过)。
export { useImagePreview, type ImagePreviewItem } from "@/components/app/imagePreviewContext";

/** 关闭键的悬停说明往下出,画在大图那一层之上(见 tooltip 的 HintRegion `layer`)。 */
const LIGHTBOX_REGION = { side: "bottom" as const, layer: "lightbox" as const };
/** 视频四周留出的边:上面是计数和「打开原图」那一条,下面是标题。留出来的这一圈就是点了关掉的背景。 */
const VIDEO_MARGIN = { x: 32, y: 64 };
/** 视频的自然尺寸还没读到时先按 16:9 摆。 */
const VIDEO_FALLBACK = { width: 16, height: 9 };

/** 视频按自己的宽高比收进视口(留出 VIDEO_MARGIN),放大缩小都按比例。 */
export function fitVideo(natural: { width: number; height: number } | undefined, viewport: { width: number; height: number }) {
  const { width, height } = natural && natural.width > 0 && natural.height > 0 ? natural : VIDEO_FALLBACK;
  const room = { width: Math.max(1, viewport.width - VIDEO_MARGIN.x * 2), height: Math.max(1, viewport.height - VIDEO_MARGIN.y * 2) };
  const scale = Math.min(room.width / width, room.height / height);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

export function ImagePreviewProvider({ children }: { children: React.ReactNode }) {
  const t = useI18n();
  const portalHostRef = React.useRef<HTMLDivElement>(null);
  const [images, setImages] = React.useState<ImagePreviewItem[]>([]);
  const [index, setIndex] = React.useState(0);
  const [visible, setVisible] = React.useState(false);
  //: 打开那一刻的视口大小 —— 视频那一项按它出盒子(见下面 width/height 那段)。
  const [viewport, setViewport] = React.useState({ width: 1280, height: 720 });
  //: 视频读到的自然尺寸(按地址记):播放器照它的宽高比收进视口,四周露出来的才是背景
  const [videoSizes, setVideoSizes] = React.useState<Record<string, { width: number; height: number }>>({});
  const closeButton = React.useRef<HTMLButtonElement | null>(null);
  //: 是从哪儿点开的。关掉之后焦点回到那里 —— 用鼠标点遮罩关掉时,焦点已经掉到 body 上,
  //: 键盘用户得从页面开头重新 Tab 一遍才回得到刚才那张图。
  const opener = React.useRef<HTMLElement | null>(null);
  const shown = React.useRef(false);
  React.useEffect(() => {
    shown.current = visible;
  }, [visible]);

  const openImagePreview = React.useCallback((next: ImagePreviewState) => {
    //: 已经开着时再点(回车又按了一下那颗按钮)不换来处:此刻的焦点可能已经不在原处了。
    if (!shown.current) opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
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
  const close = React.useCallback(() => {
    setVisible(false);
    const back = opener.current;
    opener.current = null;
    const now = document.activeElement;
    //: 只在焦点**丢了**的时候还回去(落在 body 上,或者落在灯箱自己身上)。用户在灯箱开着时
    //: 已经把焦点挪去了别处,那是他的选择,不抢。
    const lost = !now || now === document.body || Boolean(portalHostRef.current?.contains(now));
    if (back?.isConnected && lost) back.focus({ preventScroll: true });
  }, []);
  //: 内嵌浏览器、ComfyUI 工作台亮着时,原生网页视图盖在一切 DOM 上:大图开着的这段时间请它挪到窗口外(见 nativeViewAside)
  useNativeViewAside(visible);
  const reset = React.useCallback(() => setImages([]), []);
  //: 一打开焦点就在关闭键上:键盘用户回车 / 空格就能关(Esc 照旧),关掉后焦点回到点开它的地方(见 close)
  React.useEffect(() => {
    if (visible) closeButton.current?.focus({ preventScroll: true });
  }, [visible]);

  //: 手写 DOM 的界面(笔记编辑器里的图片、Markdown 正文里的图)从这里进来,见 image-preview-request。
  React.useEffect(() => {
    const onRequest = (event: Event) => openImagePreview((event as CustomEvent<ImagePreviewRequest>).detail);
    document.addEventListener(IMAGE_PREVIEW_EVENT, onRequest);
    return () => document.removeEventListener(IMAGE_PREVIEW_EVENT, onRequest);
  }, [openImagePreview]);

  //: **Esc 先只关灯箱。** 灯箱常常是从一个弹窗、画板面板、检查器里点开的,它们各自也听 Esc:
  //: Radix 弹窗在 document 的捕获阶段听,画板的面板、工作流检查器在 window 上听,灯箱自己在 window
  //: 的冒泡阶段听 —— 一下 Esc 就把灯箱和底下那一层一起关掉,用户得重新打开刚才那个弹窗。
  //: 在 window 的捕获阶段(整条事件路径的第一站)接住并就此打住,底下谁都收不到这一下;
  //: 灯箱关掉之后,下一下 Esc 才轮到它们。
  React.useEffect(() => {
    if (!visible) return;
    return listenKeys(
      window,
      (event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        event.stopImmediatePropagation();
        close();
      },
      true,
    );
  }, [visible, close]);

  const value = React.useMemo<ImagePreviewContextValue>(
    () => ({ openImagePreview, isImagePreviewOpen: visible }),
    [openImagePreview, visible],
  );

  return (
    <ImagePreviewContext.Provider value={value}>
      {children}
      {/* Radix Dialog 会把 body 设成 pointer-events:none，只给自己的 Content 恢复交互。
       * 灯箱若直接 portal 到 body，保留下层 Dialog 后就会“看得见但点不动”。专用宿主明确
       * 恢复顶层交互；关闭动画开始时立即禁用，避免透明 Portal 短暂挡住应用。 */}
      {/* 宿主也是「窗口外壳」(APP_CHROME):在大图上点的每一下(翻页、关闭、点遮罩)都发生在底下那个弹窗**外面**,
          没有它,Radix 会把这一下当成「点了弹窗外面」把弹窗一起关掉;焦点落进来(「打开原图」)也不被弹窗拽回去。 */}
      {/* 关闭键:**每一张都有、一直看得见**,在右上角,能用键盘按。不用库自带的那个 ✕ —— 它在顶上那一条里,点一下画面
          (视频的播放 / 暂停也算)那一条就淡出去,而视频铺满时又没有背景可点:只剩 Esc 关得掉(维护者报的)。 */}
      <div
        ref={portalHostRef}
        data-image-preview-portal-host
        {...APP_CHROME}
        style={{ pointerEvents: visible ? "auto" : "none" }}
      >
        {visible && (
          <HintRegion.Provider value={LIGHTBOX_REGION}>
            <IconButton
              unstyled
              ref={closeButton}
              type="button"
              label={t("imagePreviewClose")}
              shortcut="Esc"
              data-image-preview-close=""
              onClick={close}
              className="fixed right-2 top-1.5 z-[221] grid size-9 cursor-pointer place-items-center rounded-full border-0 bg-[rgb(0_0_0/0.38)] text-[rgb(255_255_255/0.88)] transition-colors hover:bg-[rgb(255_255_255/0.2)] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgb(255_255_255/0.8)] [.is-desktop_&]:[-webkit-app-region:no-drag]"
            >
              <X size={18} />
            </IconButton>
          </HintRegion.Provider>
        )}
      </div>
      <PhotoSlider
        portalContainer={portalHostRef.current ?? undefined}
        images={images.map((item) => ({
          key: item.src,
          //: **视频那一项不给 src。** 库里 render 的优先级比 src 低(它的注释原话),给了
          //: src 就走 <img> 那条路 —— 一个视频地址当图片加载,结果是整块空白。
          src: item.video ? undefined : item.src,
          overlay: item.title ?? t("imagePreviewTitle"),
          //: 自定义渲染要**显式给尺寸**:那一层按图片的自然宽高摆位,视频这边它测不到,
          //: 不给就是 0×0(一片空白),给死一个 1920×1080 又会顶出视口。给**视口大小** ——
          //: 于是它摆出来的盒子正好铺满屏幕,播放器在里面按视频自己的宽高比收在正中(fitVideo)。
          //:
          //: 不能用 position: fixed 自己铺满:这块内容住在一个带 transform 的容器里,而祖先
          //: 一旦有 transform,它就成了后代 fixed 的包含块 —— 视频会跑到屏幕角上去(实测)。
          width: item.video ? viewport.width : undefined,
          height: item.video ? viewport.height : undefined,
          //: 视频交给**自己写的**播放器,不是原生 controls —— 浏览器自带那条控件各家各的
          //: 样子、不吃主题,而画板节点上早就换掉了它,大图里又冒出来就是两套东西。
          //: 盒子用库给的属性(尺寸、淡入淡出、按下算「点了画面」),但不要它给图片的那身样子(圆角、描边):盒子铺满视口。
          //: 播放器四周露出来的是背景,点那里关掉(和图片点背景一样);点在播放器里(画面、控件条)只管播放,不关。
          render: item.video
            ? ({ attrs: { className: _photoLook, ...attrs } }) => (
                <div
                  {...attrs}
                  data-video-backdrop=""
                  className="grid place-items-center"
                  onClick={(event) => {
                    if (event.target === event.currentTarget) close();
                  }}
                >
                  {/* 直接用共用播放器,不借画板那个包装:画板那层管的是「离屏就卸掉」,
                      而这里是屏幕正中唯一的那个播放器,没有"离屏"可言。 */}
                  <div data-video-frame="" style={fitVideo(videoSizes[item.src], viewport)}>
                    <VideoPlayer
                      assetSrc={item.src}
                      autoPlay
                      className="rounded-lg"
                      onNaturalSize={(width, height) =>
                        setVideoSizes((current) =>
                          current[item.src]?.width === width && current[item.src]?.height === height
                            ? current
                            : { ...current, [item.src]: { width, height } })}
                    />
                  </div>
                </div>
              )
            : undefined,
        }))}
        index={index}
        onIndexChange={setIndex}
        visible={visible && images.length > 0}
        onClose={close}
        afterClose={reset}
        // react-photo-view 自带的样式在 vendor 层(见 design/tokens.css 开头),工具类压得过它,不用加 `!`。
        // 选中它内部结构时,类名里的 `__` 要写成 `\_\_`(整串 String.raw):Tailwind 会把任意值里的
        // `_` 换成空格,不转义的话选择器选不中任何东西。
        // 关闭后这层还会在 DOM 里留一会儿(等它自己的收尾动画),期间虽然看不见却仍然接管
        // 点击 —— 表现为「关掉大图后有一小段时间画布点不动、节点拖不了」。不可见就不该拦事件。
        // 层级压过窗口外壳(内嵌浏览器、工作台的顶栏和侧栏是 z-200,里面的说明 z-210):大图是整窗的,从侧栏里点开的
        // 也该盖住侧栏。开着时整块不当拖拽区 —— 顶栏是拖拽区,而关闭键、计数就摆在它那一条上(见 styles.css 的说明)。
        className={cn(
          !visible && "pointer-events-none",
          visible && "[.is-desktop_&]:[-webkit-app-region:no-drag]",
          //: 库自带的 ✕ 藏起来(换成上面那颗一直在的关闭键),右边让出它的位置
          String.raw`[&_.PhotoView-Slider\_\_BannerRight>.PhotoView-Slider\_\_toolbarIcon]:hidden [&_.PhotoView-Slider\_\_BannerRight]:pr-12`,
          String.raw`z-[220] [&_.PhotoView-Slider\_\_BannerWrap]:h-12 [&_.PhotoView-Slider\_\_BannerWrap]:bg-[linear-gradient(to_bottom,rgb(0_0_0/0.42),transparent)] [&_.PhotoView-Slider\_\_Counter]:font-mono [&_.PhotoView-Slider\_\_Counter]:text-ui-xs [&_.PhotoView-Slider\_\_Counter]:text-[rgb(255_255_255/0.68)] [&_.PhotoView-Slider\_\_toolbarIcon]:h-9 [&_.PhotoView-Slider\_\_toolbarIcon]:w-9 [&_.PhotoView-Slider\_\_toolbarIcon]:text-[rgb(255_255_255/0.82)] [&_:is(.PhotoView-Slider\_\_ArrowLeft,.PhotoView-Slider\_\_ArrowRight)]:text-[rgb(255_255_255/0.78)]`,
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
            <Truncate as="div" className="fixed bottom-[22px] left-1/2 max-w-[min(760px,calc(100vw-64px))] -translate-x-1/2 rounded-full border border-[rgb(255_255_255/0.14)] bg-[rgb(0_0_0/0.38)] px-[13px] py-[7px] text-ui-sm font-semibold text-white backdrop-blur-[10px]">
              {overlay}
            </Truncate>
          ) : null
        }
      />
    </ImagePreviewContext.Provider>
  );
}
