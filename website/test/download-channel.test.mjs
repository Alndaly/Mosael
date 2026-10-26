import assert from "node:assert/strict";
import test from "node:test";

import {
  channelHref,
  chinaAvailable,
  defaultChannel,
  detectChannel,
  storedChannel,
} from "../src/lib/download-channel.ts";

const MIRROR = { url: "https://pan.baidu.com/s/1example", code: "ab12" };
const NONE = { url: "", code: "" };
const RELEASES = "https://github.com/Alndaly/Mosael/releases/latest";

test("没配 R2 时中国大陆时区走网盘,其余走 GitHub", () => {
  assert.equal(detectChannel({ timeZone: "Asia/Shanghai" }, MIRROR), "baidu");
  assert.equal(detectChannel({ timeZone: "Asia/Urumqi" }, MIRROR), "baidu");
  // 港澳台归 GitHub:那边访问 GitHub 通常没问题,网盘反而要多装一个客户端。
  for (const zone of ["Asia/Hong_Kong", "Asia/Taipei", "Asia/Macau", "America/New_York", "Europe/Berlin"]) {
    assert.equal(detectChannel({ timeZone: zone, languages: ["zh-CN"] }, MIRROR), "global", zone);
  }
});

test("拿不到时区才看语言:简体算国内,繁体不算", () => {
  assert.equal(detectChannel({ languages: ["zh-CN", "en"] }, MIRROR), "baidu");
  assert.equal(detectChannel({ languages: ["zh-Hans-CN"] }, MIRROR), "baidu");
  assert.equal(detectChannel({ languages: ["zh-TW"] }, MIRROR), "global");
  assert.equal(detectChannel({ languages: [] }, MIRROR), "global");
});

test("网盘链接没配好时,谁都走 GitHub —— 不给一个点了打不开的按钮", () => {
  assert.equal(chinaAvailable(NONE), false);
  assert.equal(chinaAvailable({ url: "pan.baidu.com/s/1x", code: "" }), false, "不是 https 的不算");
  assert.equal(detectChannel({ timeZone: "Asia/Shanghai" }, NONE), "global");
  assert.equal(defaultChannel("zh", NONE), "global");
  assert.equal(storedChannel("china", NONE), null, "存过国内、后来链接撤了:按没选过处理");
  assert.equal(channelHref("china", NONE, RELEASES), RELEASES);
});

test("访客自己选过的优先,认不出的值当没选过", () => {
  assert.equal(storedChannel("global", MIRROR), "global");
  assert.equal(storedChannel("china", MIRROR), "china");
  assert.equal(storedChannel("mars", MIRROR), null);
  assert.equal(storedChannel(null, MIRROR), null);
});

test("首屏默认值只看页面语言,链接按渠道给", () => {
  assert.equal(defaultChannel("zh", MIRROR), "baidu");
  assert.equal(defaultChannel("en", MIRROR), "global");
  assert.equal(channelHref("china", MIRROR, RELEASES), MIRROR.url);
  assert.equal(channelHref("global", MIRROR, RELEASES), RELEASES);
});

test("R2 是境内主源,GitHub 与网盘各自保留备用语义", () => {
  const direct = { url: "https://dl.example.com/mosael/" };
  assert.equal(detectChannel({ timeZone: "Asia/Shanghai" }, MIRROR, direct), "china");
  assert.equal(defaultChannel("zh", MIRROR, direct), "china");
  assert.equal(storedChannel("china", MIRROR, direct), "china");
  assert.equal(storedChannel("baidu", MIRROR, direct), "baidu");
  assert.equal(channelHref("china", MIRROR, RELEASES, direct), direct.url);
  assert.equal(channelHref("baidu", MIRROR, RELEASES, direct), MIRROR.url);
  assert.equal(channelHref("global", MIRROR, RELEASES, direct), RELEASES);
});
