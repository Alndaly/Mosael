/**
 * 从平台发布接口的响应里认出作品 ID。响应样本按各平台发布接口的返回形状写,只保留相关字段。
 */
import { describe, expect, it } from "vitest";

import { findPost, postEndpoint } from "./publishedPost";

describe("认出发出去的那一条作品", () => {
  it("抖音:19 位的 item_id 按原文取,不经 JS 数字丢精度", () => {
    const body = '{"status_code":0,"item_id":7420000000000000123,"encrypt_uid":"x"}';
    const post = findPost("douyin", [{ url: "https://creator.douyin.com/web/api/media/aweme/create_v2/?a=1", body }]);
    expect(post).toEqual({
      post_id: "7420000000000000123",
      url: "https://www.douyin.com/video/7420000000000000123",
      ids: { item_id: "7420000000000000123" },
    });
    expect(String(JSON.parse(body).item_id)).not.toBe("7420000000000000123"); // parse 会丢,正是为什么不 parse
  });

  it("B 站:bvid 优先,aid 一起记下", () => {
    const body = '{"code":0,"message":"0","data":{"aid":170001,"bvid":"BV17x411w7KC"}}';
    const post = findPost("bilibili", [{ url: "https://member.bilibili.com/x/vu/web/add/v3?csrf=abc", body }]);
    expect(post?.post_id).toBe("BV17x411w7KC");
    expect(post?.ids).toEqual({ bvid: "BV17x411w7KC", aid: "170001" });
    expect(post?.url).toBe("https://www.bilibili.com/video/BV17x411w7KC");
  });

  it("小红书:只收 24 位十六进制的笔记 ID,别的 id 字段不当真", () => {
    const body = '{"success":true,"data":{"id":"66f1a2b3c4d5e6f708192a3b"},"share_link":"x","code":{"id":"42"}}';
    const post = findPost("xiaohongshu", [{ url: "https://edith.xiaohongshu.com/web_api/sns/v2/note", body }]);
    expect(post?.post_id).toBe("66f1a2b3c4d5e6f708192a3b");
    expect(post?.url).toBe("https://www.xiaohongshu.com/explore/66f1a2b3c4d5e6f708192a3b");
  });

  it("只认发布接口的响应:别的请求里的 ID 不算", () => {
    const body = '{"item_id":"7420000000000000999"}';
    expect(findPost("douyin", [{ url: "https://creator.douyin.com/web/api/media/aweme/list/", body }])).toBeNull();
  });

  it("接口没读到时,用适配器在页面上确认过的 ID(YouTube 详情页的 youtu.be 链接)", () => {
    const post = findPost("youtube", [], "dQw4w9WgXcQ");
    expect(post).toEqual({ post_id: "dQw4w9WgXcQ", url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ", ids: { videoId: "dQw4w9WgXcQ" } });
  });

  it("什么都没读到就交空,不编", () => {
    expect(findPost("tiktok", [])).toBeNull();
    expect(findPost("youtube", [], "not-an-id")).toBeNull();
    expect(findPost("mock", [{ url: "x", body: '{"item_id":"1"}' }])).toBeNull();
    expect(postEndpoint("mock")).toBeNull();
  });
});
