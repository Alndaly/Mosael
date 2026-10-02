/**
 * 合成器的解码资源池。
 *
 * 一小时的访谈切成几十段,此前每段一个独立的源:各自整份下载代理、各自解析、各自一个解码器;预热
 * 窗口里新段的整份下载赶不上,跨切点就黑一下。现在同一素材只有一份样本表 + 缓存,解码游标在切点
 * 两侧接力。
 *
 * 媒体与游标换成记账用的假对象(真实的取数 / 解码见 ProxyVideoSource.test、mp4Index.test),
 * 这里钉的是池子的分配策略。
 */
import { describe, expect, it } from "vitest";

import type { ProxyMedia, ProxyVideoSource } from "./ProxyVideoSource";
import { VideoSourcePool, type WantedSource } from "./videoSourcePool";

class FakeMedia {
  retainedBytes = 0;
  closed = false;
  constructor(readonly url: string) {}
  close() {
    this.closed = true;
  }
}

class FakeCursor {
  position = 0;
  ok = true;
  ownerKey: string | null = null;
  closed = false;
  constructor(readonly media: FakeMedia) {}
  assign(key: string) {
    this.ownerKey = key;
  }
  release() {}
  close() {
    this.closed = true;
  }
}

function makePool(budget = 96 * 1024 * 1024) {
  const medias: FakeMedia[] = [];
  const cursors: FakeCursor[] = [];
  const pool = new VideoSourcePool(budget, {
    media: (url) => {
      const media = new FakeMedia(url);
      medias.push(media);
      return media as unknown as ProxyMedia;
    },
    cursor: (media) => {
      const cursor = new FakeCursor(media as unknown as FakeMedia);
      cursors.push(cursor);
      return cursor as unknown as ProxyVideoSource;
    },
  });
  return { pool, medias, cursors };
}

const want = (clip: string, asset: string, target = 0): WantedSource => ({
  clipKey: `${clip}::${asset}`,
  mediaKey: asset,
  url: `/assets/${asset}/proxy`,
  target,
});
const cursorOf = (pool: VideoSourcePool, clip: string, asset: string) =>
  pool.sourceFor(`${clip}::${asset}`) as unknown as FakeCursor;

describe("同一素材切成几十段", () => {
  it("一路播过 40 个切点:样本表只读一份,解码器始终两个(当前段 + 预热下一段)", () => {
    const { pool, medias, cursors } = makePool();
    for (let i = 0; i < 40; i++) {
      // 第 i 段在播,第 i+1 段在预热窗口里。
      pool.sync([want(`c${i}`, "interview", i * 10), want(`c${i + 1}`, "interview", (i + 1) * 10)]);
      cursorOf(pool, `c${i}`, "interview").position = i * 10 + 9;
    }
    expect(medias).toHaveLength(1);
    expect(cursors).toHaveLength(2);
    expect(pool.stats).toEqual({ liveMedia: 1, idleMedia: 0, cursors: 2 });
  });

  it("跨切点时,预热好的那个游标直接成为当前段的 —— 不换游标、不重新起步", () => {
    const { pool } = makePool();
    pool.sync([want("a", "interview", 0), want("b", "interview", 20)]);
    const primed = cursorOf(pool, "b", "interview");
    pool.sync([want("b", "interview", 20), want("c", "interview", 40)]);
    expect(cursorOf(pool, "b", "interview")).toBe(primed);
  });

  it("挑空闲游标时,停在目标前不远的优先(接着往后解就到,不用 seek)", () => {
    for (const [target, expected] of [[50, 49], [121, 120]] as const) {
      const { pool } = makePool();
      pool.sync([want("a", "v", 0), want("b", "v", 100), want("c", "v", 200)]);
      cursorOf(pool, "a", "v").position = 49;
      cursorOf(pool, "b", "v").position = 120;
      // a、b 同一拍离场,d 同一拍进场:两个刚腾出来的游标里挑停得最近的那个。
      pool.sync([want("c", "v", 200), want("d", "v", target)]);
      expect(cursorOf(pool, "d", "v").position).toBe(expected);
    }
  });

  it("倒着拖回上一段:优先拿回它自己用过的那个游标(兜底帧还是它的画面)", () => {
    const { pool } = makePool();
    pool.sync([want("a", "v", 0)]);
    const own = cursorOf(pool, "a", "v");
    pool.sync([want("b", "v", 30)]);
    pool.sync([want("a", "v", 5)]);
    expect(cursorOf(pool, "a", "v")).toBe(own);
  });
});

describe("同一素材同时在两层", () => {
  it("画中画套自己:两个片段各一个游标(一个游标同一时刻只能在一个位置),样本表仍是一份", () => {
    const { pool, medias } = makePool();
    pool.sync([want("base", "v", 10), want("pip", "v", 3)]);
    expect(cursorOf(pool, "base", "v")).not.toBe(cursorOf(pool, "pip", "v"));
    expect(medias).toHaveLength(1);
  });
});

describe("不在场的素材", () => {
  it("离场后进闲置池(游标关掉,样本表留着),回来时不用重读", () => {
    const { pool, medias, cursors } = makePool();
    pool.sync([want("a", "x")]);
    pool.sync([want("b", "y")]);
    expect(cursors[0].closed).toBe(true);
    expect(pool.stats.idleMedia).toBe(1);
    pool.sync([want("a2", "x")]);
    expect(medias.filter((m) => m.url.includes("/x/"))).toHaveLength(1);
  });

  it("闲置池按占用字节淘汰,最久没用的先走", () => {
    const MB = 1024 * 1024;
    const { pool, medias } = makePool(64 * MB);
    pool.sync([want("a", "x")]);
    medias[0].retainedBytes = 40 * MB;
    pool.sync([want("b", "y")]);
    medias[1].retainedBytes = 40 * MB;
    pool.sync([want("c", "z")]);
    // x、y 都闲置,共 80MB > 64MB:先停的 x 被关掉。
    expect(medias[0].closed).toBe(true);
    expect(medias[1].closed).toBe(false);
  });

  it("关池子时全部释放", () => {
    const { pool, medias, cursors } = makePool();
    pool.sync([want("a", "x"), want("b", "y")]);
    pool.close();
    expect(medias.every((m) => m.closed)).toBe(true);
    expect(cursors.every((c) => c.closed)).toBe(true);
    expect(pool.sourceFor("a::x")).toBeUndefined();
  });
});
