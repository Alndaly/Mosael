import React from "react";
import { Check, ChevronDown, Search, Trash2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface AgentSessionChoice {
  id: string;
  title: string;
}

/**
 * 常驻智能体窗口的标题也是会话入口。
 *
 * 标题本身保持扁平，不再套一个输入框式外壳；只有展开后才出现承载搜索和列表的浮层。
 */
export function AgentSessionSwitcher<T extends AgentSessionChoice>({
  sessions,
  activeSession,
  deleting,
  onSelect,
  onDelete,
}: {
  sessions: readonly T[];
  activeSession: T | null;
  deleting: boolean;
  onSelect: (id: string) => void;
  onDelete: (session: T) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const keyword = query.trim().toLocaleLowerCase();
  const visibleSessions = React.useMemo(
    () =>
      keyword
        ? sessions.filter((session) => session.title.toLocaleLowerCase().includes(keyword))
        : sessions,
    [keyword, sessions],
  );

  const setMenuOpen = (next: boolean) => {
    setOpen(next);
    if (!next) setQuery("");
  };

  const title = activeSession?.title || t("chatNewSession");

  return (
    <Popover open={open} onOpenChange={setMenuOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="group/session flex h-7 w-full min-w-0 max-w-full cursor-pointer items-center gap-1 overflow-hidden border-0 bg-transparent px-0 text-left text-ui-sm font-semibold text-foreground hover:text-primary"
          aria-label={t("wfAgentSessions")}
          title={title}
        >
          <span className="min-w-0 truncate">{title}</span>
          <span className="grid size-[18px] shrink-0 place-items-center rounded-md text-muted-foreground transition-colors group-hover/session:bg-secondary group-hover/session:text-foreground">
            <ChevronDown size={11} className={cn("transition-transform duration-100", open && "rotate-180")} />
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="z-[120] w-[min(360px,calc(100vw-32px))] overflow-hidden border-0 bg-popover/95 p-0 shadow-[var(--shadow-raised)] supports-[backdrop-filter]:backdrop-blur-xl"
        aria-label={t("wfAgentSessions")}
      >
        <label className="flex h-9 items-center gap-2 border-b border-border px-2.5 text-muted-foreground focus-within:text-foreground">
          <Search size={13} className="shrink-0" aria-hidden="true" />
          <input
            autoFocus
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("chatSearchSessions")}
            aria-label={t("chatSearchSessions")}
            className="min-w-0 flex-1 border-0 bg-transparent p-0 text-ui-sm text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:appearance-none"
          />
        </label>
        <div className="max-h-[min(280px,var(--radix-popover-content-available-height))] overflow-y-auto p-1.5">
          {visibleSessions.length === 0 ? (
            <p className="m-0 px-2.5 py-5 text-center text-ui-sm text-muted-foreground">
              {t("chatSearchNoMatch")}
            </p>
          ) : (
            visibleSessions.map((session) => (
              <div
                key={session.id}
                className={cn(
                  "grid grid-cols-[minmax(0,1fr)_28px] items-center gap-1 rounded-md hover:bg-secondary",
                  session.id === activeSession?.id && "bg-secondary",
                )}
              >
                <button
                  type="button"
                  className="flex min-w-0 cursor-pointer items-center justify-between gap-2.5 border-0 bg-transparent py-2 pl-2.5 pr-2 text-left text-ui-md text-inherit [&_span]:min-w-0 [&_span]:truncate [&_svg]:shrink-0 [&_svg]:text-primary"
                  onClick={() => {
                    setMenuOpen(false);
                    onSelect(session.id);
                  }}
                >
                  <span>{session.title}</span>
                  {session.id === activeSession?.id && <Check size={13} />}
                </button>
                <button
                  type="button"
                  className="inline-flex size-[26px] cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] hover:text-destructive disabled:cursor-default disabled:opacity-45"
                  aria-label={`${t("delete")}: ${session.title}`}
                  title={t("delete")}
                  disabled={deleting}
                  onClick={(event) => {
                    event.stopPropagation();
                    setMenuOpen(false);
                    onDelete(session);
                  }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
