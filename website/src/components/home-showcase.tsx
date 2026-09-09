"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Box, PanelsTopLeft, Scissors } from "lucide-react";

import { cn } from "@/lib/utils";

export type ShowcaseWindow = {
  id: "boards" | "editor" | "scenes";
  src: string;
  label: string;
  alt: string;
  description: string;
  href: string;
};

const icons = { boards: PanelsTopLeft, editor: Scissors, scenes: Box };

/** Real screenshots stay intact; only the surrounding window layout changes. */
export function HomeShowcase({ windows, label, explore }: {
  windows: ShowcaseWindow[];
  label: string;
  explore: string;
}) {
  const [active, setActive] = useState<ShowcaseWindow["id"]>("scenes");
  const current = windows.find((window) => window.id === active)!;
  const back = windows.filter((window) => window.id !== active);

  return (
    <div aria-label={label} className="relative">
      <div className="mb-7 flex justify-center gap-1 sm:gap-3" role="group" aria-label={label}>
        {windows.map((window) => {
          const Icon = icons[window.id];
          return (
            <button key={window.id} type="button" aria-pressed={active === window.id}
              onClick={() => setActive(window.id)}
              className={cn("inline-flex min-h-11 items-center gap-2 border-b-2 px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring sm:px-5",
                active === window.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:border-border hover:text-foreground")}>
              <Icon className="size-4 shrink-0" aria-hidden />{window.label}
            </button>
          );
        })}
      </div>
      <div className="relative aspect-[1440/940] sm:aspect-[1.52]" data-showcase-stage>
        {windows.map((window) => {
          const front = window.id === active;
          const left = back[0]?.id === window.id;
          return (
            <button key={window.id} type="button" onClick={() => setActive(window.id)}
              aria-label={window.label} aria-pressed={front} tabIndex={-1}
              className={cn("absolute overflow-hidden rounded-lg border border-black/8 bg-card shadow-[0_18px_50px_-16px_rgba(26,17,48,0.4)] transition-[left,top,width,transform] duration-500 motion-reduce:transition-none sm:rounded-xl dark:border-white/10 dark:shadow-[0_18px_50px_-16px_rgba(0,0,0,0.8)]",
                front ? "inset-x-0 top-0 z-30 w-full cursor-default sm:top-[25%] sm:left-[17%] sm:w-[70%]" :
                  left ? "hidden cursor-pointer sm:top-[2%] sm:left-[1%] sm:z-10 sm:block sm:w-[57%] sm:-rotate-2" :
                    "hidden cursor-pointer sm:top-[6%] sm:left-[44%] sm:z-20 sm:block sm:w-[55%] sm:rotate-2")}>
              <Image src={window.src} alt={window.alt} width={2880} height={1880}
                sizes="(max-width: 639px) 95vw, (max-width: 1536px) 70vw, 1030px"
                loading="eager" fetchPriority={window.id === "scenes" ? "high" : "auto"}
                className="block h-auto w-full" />
            </button>
          );
        })}
      </div>
      <div className="mx-auto mt-6 flex max-w-3xl flex-col items-center gap-3 text-center text-sm sm:mt-8">
        <p className="m-0 leading-6 text-muted-foreground" aria-live="polite">{current.description}</p>
        <Link href={current.href} className="inline-flex min-h-11 items-center gap-2 font-semibold text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring">
          {explore} {current.label}<ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
    </div>
  );
}
