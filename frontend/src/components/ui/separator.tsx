import React from "react";

import { cn } from "@/lib/utils";

type SeparatorProps = Omit<React.ComponentProps<"div">, "role"> & {
  orientation?: "horizontal" | "vertical";
  decorative?: boolean;
};

/** A low-emphasis boundary between related regions, without introducing another container. */
export function Separator({
  className,
  orientation = "horizontal",
  decorative = true,
  ...props
}: SeparatorProps) {
  return (
    <div
      data-slot="separator"
      role={decorative ? "presentation" : "separator"}
      aria-orientation={decorative ? undefined : orientation}
      className={cn(
        "shrink-0 bg-border",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
      {...props}
    />
  );
}
