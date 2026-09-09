import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { CANVAS_GLASS_SURFACE_CLASS } from "./canvasPanelLayout";
import { cn } from "@/lib/utils";

/** Keep one row; explicit scroll controls reveal tools in narrow windows. */
export function CanvasToolbar({
  label,
  children,
  end,
  className,
  ...props
}: ComponentProps<"div"> & { label: string; end?: ReactNode }) {
  const t = useI18n();
  const area = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState({
    overflow: false,
    left: false,
    right: false,
  });

  useEffect(() => {
    const available = area.current;
    const track = viewport.current;
    const items = content.current;
    if (!available || !track || !items) return;
    const measure = () => {
      const overflow = items.scrollWidth > available.clientWidth + 1;
      const next = {
        overflow,
        left: overflow && track.scrollLeft > 1,
        right:
          overflow &&
          track.scrollLeft + track.clientWidth < track.scrollWidth - 1,
      };
      setScroll((previous) =>
        previous.overflow === next.overflow &&
        previous.left === next.left &&
        previous.right === next.right
          ? previous
          : next,
      );
    };
    const observer = new ResizeObserver(measure);
    observer.observe(available);
    observer.observe(track);
    observer.observe(items);
    track.addEventListener("scroll", measure, { passive: true });
    measure();
    return () => {
      observer.disconnect();
      track.removeEventListener("scroll", measure);
    };
  }, []);

  const move = (direction: number) => {
    const track = viewport.current;
    if (track)
      track.scrollBy({
        left: direction * track.clientWidth * 0.7,
        behavior: "smooth",
      });
  };

  return (
    <div
      {...props}
      role="group"
      aria-label={label}
      data-canvas-toolbar=""
      className={cn(
        CANVAS_GLASS_SURFACE_CLASS,
        "flex h-[42px] min-w-0 max-w-full shrink items-center rounded-lg p-1",
        className,
      )}
    >
      <div ref={area} className="flex min-w-0 items-center">
        {scroll.overflow && (
          <Button
            variant="ghost"
            size="icon-xs"
            className="shrink-0"
            disabled={!scroll.left}
            aria-label={t("canvasToolsPrevious")}
            title={t("canvasToolsPrevious")}
            onClick={() => move(-1)}
          >
            <ChevronLeft size={14} />
          </Button>
        )}
        <div
          ref={viewport}
          className="min-w-0 overflow-x-auto [scrollbar-width:none]"
        >
          <div ref={content} className="flex w-max items-center">
            {children}
          </div>
        </div>
        {scroll.overflow && (
          <Button
            variant="ghost"
            size="icon-xs"
            className="shrink-0"
            disabled={!scroll.right}
            aria-label={t("canvasToolsNext")}
            title={t("canvasToolsNext")}
            onClick={() => move(1)}
          >
            <ChevronRight size={14} />
          </Button>
        )}
      </div>
      {/* Assistant, run and document actions stay reachable without scrolling. */}
      {end && (
        <div className="ml-1 flex shrink-0 items-center border-l border-divider pl-1">
          {end}
        </div>
      )}
    </div>
  );
}

export function CanvasToolbarGroup({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex shrink-0 items-center gap-0.5 [&+&]:ml-1 [&+&]:border-l [&+&]:border-divider [&+&]:pl-1"
    >
      {children}
    </div>
  );
}
