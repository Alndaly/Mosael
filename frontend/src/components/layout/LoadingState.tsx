import { Loader2 } from "lucide-react";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

/** Fill the available page/panel, including when its parent is a plain block.
 * Inside a column with a heading, use `h-auto flex-1` for the remaining space. */
export function LoadingState({
  label,
  className,
}: {
  label?: string;
  className?: string;
}) {
  const t = useI18n();
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn(
        "flex h-full min-h-0 w-full flex-col overflow-auto",
        className,
      )}
    >
      <div className="m-auto flex max-w-full shrink-0 flex-col items-center gap-3 px-6 py-8 text-center text-ui-sm text-muted-foreground">
        <Loader2
          size={24}
          className="animate-mosael-spin motion-reduce:animate-none"
          aria-hidden="true"
        />
        <span className="break-words">{label ?? t("pageLoading")}</span>
      </div>
    </div>
  );
}
