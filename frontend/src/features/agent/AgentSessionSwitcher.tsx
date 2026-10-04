import React from "react";
import { ChevronDown, Eye, Search, Trash2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

export interface AgentSessionChoice {
  id: string;
  title: string;
  /** 同事共享来的(`false`)只能看:能切过去看,不给删(见 currentAgentSession.isViewOnly)。 */
  is_mine: boolean;
}

/**
 * 常驻智能体窗口的标题也是会话入口。
 *
 * 标题本身保持扁平，不再套一个输入框式外壳；只有展开后才出现承载搜索和列表的浮层。
 * 同事共享来的那几条带一只眼睛、没有删除 —— 和 AI 工作台的会话列表同一条规矩。
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
          className="group/session flex h-7 w-fit min-w-0 max-w-full cursor-pointer items-center gap-1 overflow-hidden border-0 bg-transparent px-0 text-left text-ui-sm font-semibold text-foreground hover:text-primary"
          aria-label={t("wfAgentSessions")}
        >
          <Truncate>{title}</Truncate>
          <span className="grid size-[18px] shrink-0 place-items-center rounded-md text-muted-foreground transition-colors group-hover/session:bg-secondary group-hover/session:text-foreground">
            <ChevronDown size={11} className={cn("transition-transform duration-100", open && "rotate-180")} />
          </span>
        </button>
      </PopoverTrigger>
      <MenuContent align="start" className="z-[120] gap-0 overflow-hidden p-0" label={t("wfAgentSessions")}>
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
        <div className="grid max-h-[min(280px,var(--radix-popover-content-available-height))] gap-0.5 overflow-y-auto p-1.5">
          {visibleSessions.length === 0 ? (
            <p className="m-0 px-2.5 py-5 text-center text-ui-sm text-muted-foreground">
              {/* 一条都没有和搜不到是两回事 —— 没输搜索词时说「没有匹配」是在答一个没人问的问题。 */}
              {t(keyword ? "chatSearchNoMatch" : "chatSessionsNone")}
            </p>
          ) : (
            visibleSessions.map((session) => (
              <div
                key={session.id}
                className={cn(
                  "grid grid-cols-[minmax(0,1fr)_28px] items-center gap-1 rounded-md",
                  session.id === activeSession?.id && "bg-secondary",
                )}
              >
                <MenuItem
                  role="menuitemradio"
                  checked={session.id === activeSession?.id}
                  label={session.title}
                  truncate
                  className="[&_svg]:text-primary"
                  onClick={() => {
                    setMenuOpen(false);
                    onSelect(session.id);
                  }}
                />
                {session.is_mine ? (
                  <IconButton
                    unstyled
                    type="button"
                    className="inline-flex size-[26px] cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-muted-foreground hover:bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] hover:text-destructive disabled:cursor-default disabled:opacity-45"
                    label={`${t("delete")}: ${session.title}`}
                    disabled={deleting}
                    onClick={(event) => {
                      event.stopPropagation();
                      setMenuOpen(false);
                      onDelete(session);
                    }}
                  >
                    <Trash2 size={13} />
                  </IconButton>
                ) : (
                  //: 同事共享来的:眼睛说明为什么没有删除、点进去为什么只能看。
                  <Hint label={t("chatSessionReadOnly")}>
                    <span role="img" aria-label={t("chatSessionReadOnly")} className="grid justify-self-center text-muted-foreground">
                      <Eye size={13} />
                    </span>
                  </Hint>
                )}
              </div>
            ))
          )}
        </div>
      </MenuContent>
    </Popover>
  );
}
