import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

//: 注册成功之后的去向。
//:
//: 维护者:「账号创建成功后 应该自动跳转到社区页面」。站点自己的信息结构里,"社区"不是一条
//: `/community` 路由 —— 站头「社区」指向 `/plugins`,插件与工作流是同一个社区的两个分区
//: (`src/components/community/community-header.tsx`)。所以目标必须是 `/plugins`,并且
//: **只写在一处**:哪天社区真有了独立入口,改那个常量就够,别让组件和测试各抄一份路径。
//:
//: 三条一起钉住行为:带语言段(`/[locale]/plugins`)、成功卡片先可见约 1.5 秒再跳、
//: 跳转**不碰 cookie**(同源客户端导航,已有会话不该因为这次跳转出任何事)。
const read = (relative) => fs.readFileSync(path.resolve(import.meta.dirname, "..", relative), "utf8");
const exists = (relative) => fs.existsSync(path.resolve(import.meta.dirname, "..", relative));

const signup = read("src/components/account/signup-form.tsx");
const redirectSource = read("src/components/account/signup-redirect.ts");
const redirect = await import("../src/components/account/signup-redirect.ts");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** 假的 next router:只记下 `push` 的目标,不真的导航。 */
function fakeRouter() {
  const pushed = [];
  return { pushed, push: (href) => pushed.push(href) };
}

test("注册成功后跳到当前语言的社区页,而且是站内真实存在的那一页", async () => {
  // 目标页真的在磁盘上 —— 跳到一条不存在的路由等于把刚注册的人送进 404。
  assert.ok(exists("src/app/[locale]/(site)/plugins/page.tsx"), "跳转目标不是站内真实页面");

  for (const locale of ["en", "zh"]) {
    const router = fakeRouter();
    const cancel = redirect.scheduleCommunityRedirect(router, locale, 5);
    assert.deepEqual(router.pushed, [], "定时器还没到期就跳了,成功卡片根本来不及出现");
    await sleep(30);
    assert.deepEqual(
      router.pushed,
      [`/${locale}/plugins`],
      `没有跳到带语言段的社区页(${locale})`,
    );
    cancel();
  }
});

test("成功卡片先可见约 1.5 秒:不是立刻消失,也不是永远不走", async () => {
  assert.ok(
    redirect.SIGNUP_REDIRECT_DELAY_MS >= 1000 && redirect.SIGNUP_REDIRECT_DELAY_MS <= 2000,
    `成功态停留时长不在合理区间:${redirect.SIGNUP_REDIRECT_DELAY_MS}ms`,
  );

  const router = fakeRouter();
  // 不传 delay:走默认值,测的就是生产上那 1.5 秒。
  const cancel = redirect.scheduleCommunityRedirect(router, "zh");
  await sleep(1000);
  assert.deepEqual(router.pushed, [], "1 秒内就跳走了 ——「账号已创建」没人看得见");
  await sleep(700);
  assert.deepEqual(router.pushed, ["/zh/plugins"], "1.5 秒后没有去社区页");
  cancel();
});

test("跳转可以被取消(离开本页 / 组件卸载后不再跳)", async () => {
  const router = fakeRouter();
  const cancel = redirect.scheduleCommunityRedirect(router, "en", 10);
  cancel();
  await sleep(40);
  assert.deepEqual(router.pushed, [], "取消之后仍然跳了 —— cleanup 没生效");
});

test("跳转不动 cookie:不读、不写、不删,也不整页刷新换个地址", () => {
  // 跳转是 `router.push`:同源客户端导航,浏览器里的 cookie 原样留着。
  const clearing = [
    [/document\.cookie\s*=/, "有脚本在写 document.cookie"],
    [/clearCookie|cookieStore\.delete/i, "有清 cookie 的调用"],
    [/cookies\(\s*\)\s*\.\s*delete/, "有 Next 的 cookies().delete"],
  ];
  for (const [pattern, why] of clearing) {
    assert.doesNotMatch(signup, pattern, `注册表单:${why}`);
    assert.doesNotMatch(redirectSource, pattern, `跳转逻辑:${why}`);
  }
  // 跳转模块本身完全不碰 cookie —— 它没有理由知道 cookie 存在。
  assert.doesNotMatch(redirectSource, /cookie/i, "跳转逻辑不该出现 cookie 相关代码");
  // 也不该用整页跳转(那会重新走一次文档加载,和"客户端导航"不是一回事)。
  assert.doesNotMatch(redirectSource, /location\.(href|assign|replace)/, "没有用整页跳转");
});

test("移动端同样跳:跳转由 phase 决定,不看视口", () => {
  assert.doesNotMatch(signup, /matchMedia|innerWidth|isMobile|useMediaQuery/, "跳转被写成了只在某种屏幕上生效");
  const effect = signup.match(/useEffect\(\(\) => \{[\s\S]*?scheduleCommunityRedirect\(router, locale\)[\s\S]*?\}, \[phase, router, locale\]\)/);
  assert.ok(effect, "成功态没有用 effect 安排跳转(或依赖不完整)");
});

test("目标只写一处、语言来自调用方,不硬编码", () => {
  assert.match(redirectSource, /\$\{locale\}/, "目标没有拼 locale 段");
  assert.doesNotMatch(redirectSource, /["'`]\/(en|zh)\//, "目标里硬编码了某种语言");
  assert.match(redirectSource, /route|push/, "没有真的调用 router.push");
  // 组件只把「当前 locale」交给 helper,自己不再拼第二份路径。
  assert.match(signup, /scheduleCommunityRedirect\(router, locale\)/, "组件没有用当前 locale 安排跳转");
  assert.match(signup, /useRouter\(\)/, "组件没有拿到 router");
  assert.doesNotMatch(signup, /router\.push\(/, "组件绕过 helper 自己拼了跳转目标");
});

test("成功卡片仍然渲染:string 先出现,再走", () => {
  assert.match(signup, /phase === "success"/, "成功态分支没了");
  assert.match(signup, /copy\.signupSuccessTitle/, "「账号已创建」标题没了");
  assert.match(signup, /copy\.signupSuccessBody/, "成功说明没了");
  // 不是「setPhase 之后马上 push」:那正是"立刻消失"。
  assert.doesNotMatch(signup, /setPhase\("success"\);\s*router\.push/, "成功卡片被立刻跳走了");
});
