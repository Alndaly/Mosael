import { ProxyMedia, ProxyVideoSource } from "./ProxyVideoSource";
import { evictions } from "./sourcePool";

/**
 * 合成器的解码资源池:素材 → 一份 {@link ProxyMedia}(样本表 + 样本数据缓存),片段 → 一个解码游标。
 *
 * 一小时的访谈切成几十段,此前每段一个独立的源:各自整份下载代理、各自解析、各自一个解码器,预热窗口
 * 里新段的整份下载根本赶不上,跨切点就黑一下。现在:
 *
 * - 同一素材的所有片段共用一份 ProxyMedia —— 样本表只读一次,样本数据按 GOP 取、共享缓存。
 * - 游标按片段分配(同一时刻要两个位置就得两个游标:画中画套自己),但片段离场时游标**不销毁**,
 *   留一个给同素材的下一段接着用 —— 切点前预热下一段时,拿的就是上一段腾出来的那个解码器。
 * - 没有片段在用的素材进闲置池,按占用字节淘汰(最久没用的先走)。
 */

export interface WantedSource {
  /** 片段的身份(含它此刻指向的那份代理的指纹,代理换了就是新的键)。 */
  clipKey: string;
  /** 素材 + 代理指纹:同一个键共用一份 ProxyMedia。 */
  mediaKey: string;
  url: string;
  /** 这个片段马上要的媒体时间(秒),挑空闲游标时用。 */
  target: number;
}

export interface PoolFactory {
  media: (url: string) => ProxyMedia;
  cursor: (media: ProxyMedia) => ProxyVideoSource;
}

const defaultFactory: PoolFactory = {
  media: (url) => new ProxyMedia(url),
  cursor: (media) => new ProxyVideoSource(media),
};

/** 每份素材在场时最多留几个空闲游标(带着活的解码器)等下一段来接。 */
const SPARE_CURSORS_PER_MEDIA = 1;
/** 空闲游标停在目标之前这么近以内,接着往后解就到,不用 seek —— 优先给它。 */
const CONTINUE_WITHIN_SEC = 2;

interface MediaEntry {
  media: ProxyMedia;
  /** 这份素材名下的全部游标;正在被片段用的记在 byClip 里,其余是空闲的。 */
  cursors: ProxyVideoSource[];
}

export class VideoSourcePool {
  private readonly live = new Map<string, MediaEntry>();
  private readonly idle = new Map<string, MediaEntry>();
  private readonly byClip = new Map<string, { mediaKey: string; source: ProxyVideoSource }>();

  constructor(
    private readonly idleBudgetBytes: number,
    private readonly factory: PoolFactory = defaultFactory,
  ) {}

  sourceFor(clipKey: string): ProxyVideoSource | undefined {
    return this.byClip.get(clipKey)?.source;
  }

  /** 让池子和「此刻要哪些片段」对齐:离场的放回素材名下,新来的分游标,不再用的素材进闲置池。 */
  sync(wanted: readonly WantedSource[]): void {
    const wantedKeys = new Set(wanted.map((item) => item.clipKey));
    for (const [clipKey, held] of this.byClip) {
      if (wantedKeys.has(clipKey)) continue;
      this.byClip.delete(clipKey);
      held.source.release();
    }
    for (const item of wanted) {
      if (this.byClip.has(item.clipKey)) continue;
      const entry = this.entryFor(item.mediaKey, item.url);
      const source = this.cursorFor(entry, item.clipKey, item.target);
      source.assign(item.clipKey);
      this.byClip.set(item.clipKey, { mediaKey: item.mediaKey, source });
    }
    this.settle();
  }

  private entryFor(mediaKey: string, url: string): MediaEntry {
    let entry = this.live.get(mediaKey);
    if (entry) return entry;
    entry = this.idle.get(mediaKey);
    if (entry) {
      this.idle.delete(mediaKey);
    } else {
      entry = { media: this.factory.media(url), cursors: [] };
    }
    this.live.set(mediaKey, entry);
    return entry;
  }

  private inUse(): Set<ProxyVideoSource> {
    return new Set([...this.byClip.values()].map((held) => held.source));
  }

  /**
   * 空闲游标里挑一个:这个片段自己上次用的那个优先(倒着拖回切点时,它的兜底帧还是对的);其次停在
   * 目标前不远的(接着解就到);再不行随便一个(要 seek,但不用新建解码器)。
   */
  private cursorFor(entry: MediaEntry, clipKey: string, target: number): ProxyVideoSource {
    const busy = this.inUse();
    const free = entry.cursors.filter((cursor) => !busy.has(cursor) && cursor.ok);
    const own = free.find((cursor) => cursor.ownerKey === clipKey);
    if (own) return own;
    const continuing = free
      .filter((cursor) => cursor.position <= target + 1e-3 && target - cursor.position <= CONTINUE_WITHIN_SEC)
      .sort((a, b) => b.position - a.position)[0];
    const chosen = continuing ?? free[0];
    if (chosen) return chosen;
    const cursor = this.factory.cursor(entry.media);
    entry.cursors.push(cursor);
    return cursor;
  }

  private settle(): void {
    const busy = this.inUse();
    const usedMedia = new Set([...this.byClip.values()].map((held) => held.mediaKey));
    for (const [mediaKey, entry] of this.live) {
      if (!usedMedia.has(mediaKey)) {
        // 没有片段在用了:游标全关(解码器是稀缺资源),样本表和缓存进闲置池,回来时不用重读。
        for (const cursor of entry.cursors) cursor.close();
        entry.cursors = [];
        this.live.delete(mediaKey);
        this.idle.delete(mediaKey);
        this.idle.set(mediaKey, entry); // 重新插入 = 最近停放的排在最后
        continue;
      }
      // 在场的素材:空闲游标留一个(带着解码器等下一段),多的关掉;坏掉的也关掉。
      let spare = 0;
      entry.cursors = entry.cursors.filter((cursor) => {
        if (busy.has(cursor)) return true;
        if (cursor.ok && spare < SPARE_CURSORS_PER_MEDIA) {
          spare += 1;
          return true;
        }
        cursor.close();
        return false;
      });
    }
    const parked = [...this.idle].map(([id, entry]) => ({ id, retainedBytes: entry.media.retainedBytes }));
    for (const id of evictions(parked, this.idleBudgetBytes)) {
      this.idle.get(id)?.media.close();
      this.idle.delete(id);
    }
  }

  /** 测试与诊断用:此刻有几份素材在内存里、多少个游标。 */
  get stats(): { liveMedia: number; idleMedia: number; cursors: number } {
    let cursors = 0;
    for (const entry of this.live.values()) cursors += entry.cursors.length;
    return { liveMedia: this.live.size, idleMedia: this.idle.size, cursors };
  }

  close(): void {
    for (const entry of [...this.live.values(), ...this.idle.values()]) {
      for (const cursor of entry.cursors) cursor.close();
      entry.media.close();
    }
    this.live.clear();
    this.idle.clear();
    this.byClip.clear();
  }
}
