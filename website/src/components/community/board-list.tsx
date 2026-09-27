"use client";

/** 公开画板列表:第一页服务端给,之后按游标在浏览器里接。 */
import { localizeTree } from "@/lib/community/localize";
import { LayoutGrid } from "lucide-react";
import * as React from "react";

import { BoardCard, GRID } from "@/components/community/cards";
import { BUTTON, Spinner, StatePanel, errorText } from "@/components/community/ui";
import { HTML_LANG, type Locale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";
import { REQUESTED, browserUrl } from "@/lib/community/endpoints";
import { errorFromResponse, networkError } from "@/lib/community/errors";
import type { Page, ShareSummary } from "@/lib/community/types";

export function BoardList({ locale, initial }: { locale: Locale; initial: Page<ShareSummary> }) {
  const t = getMessages(locale);
  const [items, setItems] = React.useState(initial.items);
  const [cursor, setCursor] = React.useState(initial.next_cursor);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const more = async () => {
    if (!cursor) return;
    setLoading(true);
    setError(null);
    try {
      let response: Response;
      try {
        response = await fetch(browserUrl(REQUESTED.publicShares({ cursor, limit: 24 })), { headers: { Accept: "application/json", "Accept-Language": HTML_LANG[locale] } });
      } catch {
        throw networkError();
      }
      if (!response.ok) throw await errorFromResponse(response);
      const page = localizeTree((await response.json()) as Page<ShareSummary>, locale);
      setItems((current) => [...current, ...page.items]);
      setCursor(page.next_cursor);
    } catch (caught) {
      setError(errorText(caught, t.community.genericError, t.community.networkError));
    } finally {
      setLoading(false);
    }
  };

  if (items.length === 0) return <StatePanel icon={<LayoutGrid className="size-7 text-muted-foreground" aria-hidden />} title={t.boards.empty} />;
  return (
    <div className="grid gap-6">
      <ul className={GRID}>
        {items.map((share) => (
          <li key={share.slug} className="grid">
            <BoardCard locale={locale} share={share} />
          </li>
        ))}
      </ul>
      {error && <p className="m-0 text-center text-sm text-destructive">{error}</p>}
      {cursor && (
        <div className="flex justify-center">
          <button type="button" onClick={() => void more()} disabled={loading} className={BUTTON.secondary}>
            {loading && <Spinner />}
            {loading ? t.community.loading : t.community.loadMore}
          </button>
        </div>
      )}
    </div>
  );
}
