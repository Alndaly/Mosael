import * as React from "react";

import { cn } from "../../lib/utils";

function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-border bg-card text-card-foreground", className)} {...props} />;
}

export { Card };
