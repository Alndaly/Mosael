import React from "react";
import { ChevronDown, ChevronRight, Eye, Search, Trash2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { openedIn, thisWasOpenedIn, type SessionHome } from "@/features/agent/homeLabel";
import { cn } from "@/lib/utils";

export interface AgentSessionChoice extends SessionHome {
  id: string;
  title: string;
  /** 同事共享来的(`false`)只能看:能切过去看,不给删(见 currentAgentSession.isViewOnly)。 */
  is_mine: boolean;
}

/**
 * 常驻智能体面板的标题也是对话入口(ADR 0044 §4)。
 *
 * 标题本身保持扁平,不套输入框式外壳;当前这段的家不在这里时(在这里接着别处开的那段),标题下一行小字说它是在哪开的。
 * 展开后的浮层:搜索框;「这里的对话」(家在这里的,最近在前);「其他对话」默认收着,展开是工作区里其余的,每行一句
 * 「在…里开的」。搜索两组一起搜,命中「其他对话」就自动展开。挑「其他对话」里的一段 = 在这里接着聊,它的家不变。
 * 同事共享来的那几条带一只眼睛、没有删除 —— 和 AI Studio 的列表同一条规矩。
 */
export function AgentSessionSwitcher<T extends AgentSessionChoice>({
  here,
  elsewhere,
  activeSession,
  homedHere,
  deleting,
  onSelect,
  onDelete,
  onOpenChange,
  openRequest,
}: {
  here: readonly T[];
  /** 工作区里其余的对话。还没取到是 `null`(展开时才取,见 `onOpenChange`)。 */
  elsewhere: readonly T[] | null;
  /** 当前这段;草稿是 `null`。 */
  activeSession: T | null;
  /** 当前这段的家就是这里吗 —— 不是就在标题下说一句它是在哪开的。 */
  homedHere: boolean;
  deleting: boolean;
  onSelect: (id: string) => void;
  onDelete: (session: T) => void;
  /** 浮层开合:开着的时候面板才去取全工作区的那份清单。 */
  onOpenChange?: (open: boolean) => void;
  /** 从外面把浮层打开(空态里那句「接着别处的对话」):变一次开一次,`elsewhere` 为真时「其他对话」一起展开。 */
  openRequest?: { nonce: number; elsewhere: boolean } | null;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [showElsewhere, setShowElsewhere] = React.useState(false);
  const keyword = query.trim().toLocaleLowerCase();
  const matches = React.useCallback(
    (session: T) => !keyword || session.title.toLocaleLowerCase().includes(keyword),
    [keyword],
  );
  const hereShown = React.useMemo(() => here.filter(matches), [here, matches]);
  const elsewhereShown = React.useMemo(() => (elsewhere ?? []).filter(matches), [elsewhere, matches]);
  //: 搜索命中「其他对话」就自动展开 —— 收着的那一组里找到了,却要再点一下才看得见,等于没找到。
  const elsewhereOpen = showElsewhere || (Boolean(keyword) && elsewhereShown.length > 0);

  const setMenuOpen = React.useCallback(
    (next: boolean) => {
      setOpen(next);
      onOpenChange?.(next);
      if (!next) {
        setQuery("");
        setShowElsewhere(false);
      }
    },
    [onOpenChange],
  );
  React.useEffect(() => {
    if (!openRequest) return;
    setMenuOpen(true);
    setShowElsewhere(openRequest.elsewhere);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRequest?.nonce]);

  const title = activeSession?.title || t("chatNewSession");

  const row = (session: T, withHome: boolean) => (
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
        description={withHome ? openedIn(t, session) : undefined}
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
  );

  const groupTitle = "px-2.5 pb-0.5 pt-1.5 text-ui-xs font-medium text-muted-foreground";
  const none = "m-0 px-2.5 py-3 text-center text-ui-sm text-muted-foreground";

  return (
    <div className="grid min-w-0">
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
          <div className="grid max-h-[min(360px,var(--radix-popover-content-available-height))] gap-0.5 overflow-y-auto p-1.5">
            <div role="group" aria-label={t("agentSessionsHere")} className="grid gap-0.5">
              <p className={cn("m-0", groupTitle)}>{t("agentSessionsHere")}</p>
              {hereShown.length === 0 ? (
                <p className={none}>{t(keyword ? "chatSearchNoMatch" : "agentSessionsHereNone")}</p>
              ) : (
                hereShown.map((session) => row(session, false))
              )}
            </div>
            <div role="group" aria-label={t("agentSessionsElsewhere")} className="grid gap-0.5 border-t border-divider pt-1">
              <button
                type="button"
                aria-expanded={elsewhereOpen}
                className={cn(groupTitle, "flex cursor-pointer items-center gap-1 rounded-md border-0 bg-transparent text-left hover:text-foreground")}
                onClick={() => setShowElsewhere((value) => !value)}
              >
                <ChevronRight size={11} className={cn("shrink-0 transition-transform duration-100", elsewhereOpen && "rotate-90")} aria-hidden />
                {t("agentSessionsElsewhere")}
              </button>
              {elsewhereOpen &&
                (elsewhere === null ? (
                  <p className={none}>{t("chatLoadingSession")}</p>
                ) : elsewhereShown.length === 0 ? (
                  <p className={none}>{t(keyword ? "chatSearchNoMatch" : "agentSessionsElsewhereNone")}</p>
                ) : (
                  elsewhereShown.map((session) => row(session, true))
                ))}
            </div>
          </div>
        </MenuContent>
      </Popover>
      {activeSession && !homedHere && (
        <Truncate as="p" className="m-0 -mt-1 text-ui-xs font-normal text-muted-foreground">
          {thisWasOpenedIn(t, activeSession)}
        </Truncate>
      )}
    </div>
  );
}
