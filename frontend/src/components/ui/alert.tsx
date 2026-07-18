import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative flex w-full items-start gap-2 rounded-md border px-3 py-2.5 text-[12.5px] leading-relaxed",
  {
    variants: {
      variant: {
        default: "border-border bg-card text-foreground",
        destructive:
          "border-destructive/40 bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] text-destructive [&>svg]:text-destructive",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />;
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("min-w-0 flex-1", className)} {...props} />;
}

export { Alert, AlertDescription };
