import * as React from "react";

import { cn } from "@/lib/utils";

/** Placeholder block for first-load states. Pulses to signal "content is coming", using the muted
    surface token so it reads as a stand-in in both light and dark. Size/shape via className. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}

export { Skeleton };
