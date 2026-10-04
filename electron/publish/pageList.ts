// 一个浏览器会话里的多个页面(像 Arc 左边那一列):先后次序、哪个是当前页、按什么找到某一页。
//
// 纯账本,不碰 Electron —— 视图怎么挂、怎么藏在 accountViews 里。拆出来是为了能直接测:「关掉当前页之后
// 落到哪一页」「第几个页面是哪个」这种规则错了,用户看到的是点了关闭跳到一个莫名其妙的页面。

/** 一个会话最多同时开多少个页面。每个页面都是一个活着的网页进程;再多既吃内存,列表也看不过来。 */
export const MAX_PAGES = 10;

export interface PageMatch {
  /** 第几个(从 1 起,列表最上面那个是 1)。 */
  index?: number;
  /** 标题里含这段(不分大小写)。 */
  title?: string;
  /** 网址里含这段(不分大小写)。 */
  url?: string;
}

export class PageList<T> {
  private entries: Array<{ id: string; item: T }> = [];
  private currentId: string | null = null;

  get size(): number {
    return this.entries.length;
  }

  get full(): boolean {
    return this.entries.length >= MAX_PAGES;
  }

  list(): ReadonlyArray<{ id: string; item: T }> {
    return this.entries;
  }

  get(id: string): T | null {
    return this.entries.find((one) => one.id === id)?.item ?? null;
  }

  idOf(item: T): string | null {
    return this.entries.find((one) => one.item === item)?.id ?? null;
  }

  current(): { id: string; item: T } | null {
    return this.entries.find((one) => one.id === this.currentId) ?? null;
  }

  /** 当前页在列表里是第几个(从 1 起);没有页面是 0。 */
  currentIndex(): number {
    return this.entries.findIndex((one) => one.id === this.currentId) + 1;
  }

  /**
   * 加一页。`after`:放在哪一页后面(新窗口跟在开它的那一页后面,像浏览器那样);不给就放最后。
   * `activate`:是否切过去(后台打开的不切)。满了不加,返回 false。
   */
  add(id: string, item: T, opts: { activate: boolean; after?: string | null }): boolean {
    if (this.full) return false;
    const at = opts.after ? this.entries.findIndex((one) => one.id === opts.after) : -1;
    if (at >= 0) this.entries.splice(at + 1, 0, { id, item });
    else this.entries.push({ id, item });
    if (opts.activate || this.currentId === null) this.currentId = id;
    return true;
  }

  setCurrent(id: string): boolean {
    if (!this.entries.some((one) => one.id === id)) return false;
    this.currentId = id;
    return true;
  }

  /**
   * 拿掉一页。拿掉的是当前页时,落到它上面那一页(它是第一页就落到新的第一页)—— 关掉一个弹出来的
   * 授权页,回到的正是开它的那一页。返回新的当前页 id(没页面了是 null)。
   */
  remove(id: string): string | null {
    const at = this.entries.findIndex((one) => one.id === id);
    if (at < 0) return this.currentId;
    this.entries.splice(at, 1);
    if (this.currentId === id) {
      this.currentId = this.entries[Math.max(0, at - 1)]?.id ?? null;
    }
    return this.currentId;
  }

  /** 按给定的 id 次序重排(拖动)。给的次序里少了谁、多了谁都不认 —— 两边看到的不是同一份列表。 */
  reorder(ids: string[]): boolean {
    if (ids.length !== this.entries.length || new Set(ids).size !== ids.length) return false;
    const byId = new Map(this.entries.map((one) => [one.id, one]));
    if (!ids.every((id) => byId.has(id))) return false;
    this.entries = ids.map((id) => byId.get(id)!);
    return true;
  }

  /** 按第几个 / 标题 / 网址找一页;找不到是 null。几个条件都给时都要满足。 */
  find(match: PageMatch, describe: (item: T) => { title: string; url: string }): string | null {
    const title = match.title?.trim().toLowerCase();
    const url = match.url?.trim().toLowerCase();
    const hit = this.entries.find((one, index) => {
      if (match.index !== undefined && match.index !== index + 1) return false;
      const page = describe(one.item);
      if (title && !page.title.toLowerCase().includes(title)) return false;
      if (url && !page.url.toLowerCase().includes(url)) return false;
      return true;
    });
    return hit?.id ?? null;
  }
}
