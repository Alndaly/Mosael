import React from "react";

/** 鼠标停多久才展开:从网页移到窗口边上一掠而过,不该弹出来。 */
const HOVER_MS = 150;
/** 移开多久才收回:指针在列表边上抖一下不算离开。 */
const LEAVE_MS = 150;

type PeekBridge = Pick<NonNullable<Window["mosaelPublish"]>, "snapshotPage" | "coverPage">;
type PageSnapshot = NonNullable<Awaited<ReturnType<PeekBridge["snapshotPage"]>>>;

/**
 * 收起的页面列表**临时展开**(像 Arc):鼠标停在图标条上、键盘切进列表时,列表展开到完整宽度,盖在网页上
 * 显示每页的标题和网址;移开、焦点离开就收回。不推挤网页 —— 左侧让出的还是图标条那么宽。
 *
 * 难处在原生网页视图盖在一切 DOM 上,展开的那一截 DOM 会被它盖住。所以展开前先拍下网页此刻的画面,铺在
 * 原处(`snapshot`,渲染成一张图);画面铺好了(`backdropReady`)再请主进程藏起原生视图 —— 看上去网页还在,
 * 列表就盖在它上面了。收回时反过来:先让原生视图亮回来,再拿掉那张画面,中间不会闪一下空白。
 *
 * `keepOpen`:别的理由让它开着(列表里的地址框开着)。在展开的列表里选了一页、开了新页面之后调 `dismiss`:
 * 马上收回让人看到那一页,鼠标移开再回来(或键盘重新切进来)才再展开。
 */
export function usePagePeek(bridge: PeekBridge, enabled: boolean, keepOpen: boolean) {
  const [hovering, setHovering] = React.useState(false);
  const [focused, setFocused] = React.useState(false);
  const [dismissed, setDismissed] = React.useState(false);
  const [snapshot, setSnapshot] = React.useState<PageSnapshot | null>(null);
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLElement | null>(null);
  //: 每次「要不要展开」变了就换一代:晚到的画面、晚到的「藏好了」认得出自己已经过时。
  const generation = React.useRef(0);
  const covered = React.useRef(false);
  const leaveTimer = React.useRef<number | undefined>(undefined);
  //: 键盘切进来、地址框开着:不用等鼠标停稳,马上展开。
  const instant = React.useRef(false);
  instant.current = focused || keepOpen;

  const wanted = enabled && !dismissed && (hovering || focused || keepOpen);

  React.useEffect(() => {
    const mine = ++generation.current;
    if (wanted) {
      const timer = window.setTimeout(
        () => {
          bridge.snapshotPage().then(
            (shot) => {
              if (shot && generation.current === mine) setSnapshot(shot);
            },
            () => undefined, // 拍不到(没有前台网页、主进程是旧的):就不展开,图标条照旧
          );
        },
        instant.current ? 0 : HOVER_MS,
      );
      return () => window.clearTimeout(timer);
    }
    setOpen(false);
    if (!covered.current) {
      setSnapshot(null);
      return;
    }
    covered.current = false;
    void bridge
      .coverPage(false)
      .catch(() => undefined)
      .then(() => {
        if (generation.current === mine) setSnapshot(null);
      });
  }, [wanted, bridge]);

  // 展开着被卸掉(回到 Mosael、换了会话):网页得亮回来。
  React.useEffect(
    () => () => {
      generation.current += 1;
      window.clearTimeout(leaveTimer.current);
      if (covered.current) void bridge.coverPage(false).catch(() => undefined);
    },
    [bridge],
  );

  /** 那张画面铺好了:藏起原生视图,列表展开。 */
  const backdropReady = React.useCallback(() => {
    const mine = generation.current;
    if (covered.current) return;
    bridge.coverPage(true).then(
      () => {
        if (generation.current !== mine) {
          void bridge.coverPage(false).catch(() => undefined); // 藏好之前就不要了
          return;
        }
        covered.current = true;
        setOpen(true);
      },
      () => undefined,
    );
  }, [bridge]);

  const dismiss = React.useCallback(() => {
    setDismissed(true);
    setFocused(false);
    const active = document.activeElement;
    if (active instanceof HTMLElement && ref.current?.contains(active)) active.blur();
  }, []);

  const handlers = {
    onMouseEnter: () => {
      window.clearTimeout(leaveTimer.current);
      setHovering(true);
      // 又移进来了:不管上回是怎么收回的(鼠标点的、键盘选的),这都是新的一次停留。
      setDismissed(false);
    },
    onMouseLeave: () => {
      window.clearTimeout(leaveTimer.current);
      const left = () => {
        setHovering(false);
        setDismissed(false);
      };
      // 还没展开就移开(一掠而过):立刻算离开,不然等展开的那一下还会到。
      if (open) leaveTimer.current = window.setTimeout(left, LEAVE_MS);
      else left();
    },
    onFocus: () => {
      setFocused(true);
      setDismissed(false);
    },
    onBlur: (event: React.FocusEvent) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false);
    },
  };

  return { ref, open, snapshot, backdropReady, dismiss, handlers };
}
