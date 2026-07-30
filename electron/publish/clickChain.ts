/**
 * 「点提交」这件事的统一做法。
 *
 * 为什么需要它:四家平台的点击各自演化出了一条降级链——小红书四条、B 站两条、视频号两条、
 * 抖音一条——语义、日志、失败模式全都不一样。于是**同一类故障**(点出去了但页面没反应)在
 * 各家表现成完全不同的样子:B 站白等 waitResult 五分钟再报「未确认发布」;视频号静默当成功;
 * 抖音抛一个没有上下文的异常。排查时每家都要重新推一遍,这次 B 站那个 bug 就是这么被拖长的。
 *
 * 为什么**不能**统一成一种点击机制(这不是没治理,是硬约束):
 *  - 真实鼠标事件(sendInputEvent → humanClickAt)`isTrusted === true`,风控友好,但要求视图有
 *    真实视口与命中测试——后台任务视图视口是 0×0,遮挡也会把点击截走;
 *  - DOM 事件(el.click / dispatchEvent)不受视口与遮挡影响,但 `isTrusted === false`,关键动作
 *    上是可被识别的自动化特征;
 *  - 小红书的发布按钮是 shadow DOM 里的自定义元素,外面根本 querySelector 不到,只能派发事件。
 *
 * 所以正确的形态是「有序降级 + 每步验证」,而不是强行只留一种机制。这个模块统一的是**流程**:
 * 先试可信的,不行再退到能点到的;每点一次都确认页面真的有反应,没反应才换下一种;日志格式
 * 一致,并且明确记下最终走的是可信路径还是降级路径(后者是风控暴露面,值得在日志里看得见)。
 */
import { plog } from "./log";
import type { PageDriver } from "./pageDriver";

/** 平台通用的「正在处理」文案:出现即说明点击已被受理,不必再换点法。 */
export const PROCESSING_TEXTS = ["正在投稿", "正在发布", "提交中", "发布中", "处理中"] as const; // i18n-ok

export interface ClickAttempt {
  /** 日志里认得出的名字,如 `css .submit-add` / `text 立即投稿`。 */
  label: string;
  /**
   * `pointer` = 真实鼠标事件(isTrusted,风控友好,但依赖视口与命中测试);
   * `dom`     = DOM 事件(点得到,但 isTrusted 为 false)。
   * 只用于日志:让「这次是降级点的」在事后看得见。
   */
  kind: "pointer" | "dom";
  click: () => Promise<void>;
}

export const pointerAttempt = (label: string, click: () => Promise<void>): ClickAttempt => ({
  label,
  kind: "pointer",
  click,
});

export const domAttempt = (label: string, click: () => Promise<void>): ClickAttempt => ({
  label,
  kind: "dom",
  click,
});

/**
 * 构造「页面是否对点击有反应」的判定。任一条件成立即算受理:
 *  - `gone`:提交控件从 DOM 里消失(成功页替换了表单);
 *  - `texts`:出现这些文案之一(处理中/成功/失败都算**有反应**——有反应就不该再点第二次);
 *  - `urlPattern`:URL 变成目标形态(抖音/视频号成功后会跳走)。
 *
 * 判定要**宽**:它的职责不是判断成功(那是 waitResult 的事),而是判断「这一下点进去了吗」。
 * 判严了会导致重复提交,而重复投稿的代价比多等一轮大得多。
 */
export function pageReacted(
  driver: PageDriver,
  opts: {
    gone?: string;
    texts?: readonly string[];
    urlPattern?: RegExp;
    timeoutMs?: number;
  },
): () => Promise<boolean> {
  const expr = reactionExpression(opts);
  const timeout = opts.timeoutMs ?? 8_000;
  return () => driver.waitForFunction(expr, timeout, 500);
}

/** 判定表达式的构造(与 driver 无关,便于单测)。 */
export function reactionExpression(opts: {
  gone?: string;
  texts?: readonly string[];
  urlPattern?: RegExp;
}): string {
  const parts: string[] = [];
  if (opts.gone) {
    parts.push(`!document.querySelector(${JSON.stringify(opts.gone)})`);
  }
  if (opts.texts?.length) {
    parts.push(
      `new RegExp(${JSON.stringify(opts.texts.join("|"))}).test((document.body && document.body.innerText) || '')`,
    );
  }
  if (opts.urlPattern) {
    parts.push(`new RegExp(${JSON.stringify(opts.urlPattern.source)}).test(location.href)`);
  }
  // 没给任何条件就恒为假:宁可报「点了没反应」,也不要凭空认为受理了。
  return parts.length ? `(${parts.join(" || ")})` : "false";
}

/** 降级链跑完仍未被受理。`clicked` 区分两种截然不同的原因,失败信息里也带上。 */
export class CommitClickError extends Error {
  constructor(
    readonly what: string,
    /** true = 点出去了但页面毫无反应(平台拒绝/校验未过);false = 一次都没点出去(元素找不到/被遮挡/禁用)。 */
    readonly clicked: boolean,
    readonly tried: readonly string[],
  ) {
    super(
      clicked
        ? `${what}: clicked but the page never reacted (tried: ${tried.join(", ")})`
        : `${what}: no clickable target (tried: ${tried.join(", ")})`,
    );
    this.name = "CommitClickError";
  }
}

/**
 * 按序尝试各种点法,每点一次都确认受理;全部失败抛 CommitClickError。
 * 返回最终生效的那次尝试的 label。
 */
/**
 * 受理判定的**自检**:点击之前先量一次。
 *
 * 如果它在点击**之前**就已经为真,那它区分不了任何东西 —— 之后无论点没点、点成没成,它都会立刻
 * 说「受理了」。
 *
 * 这类「判定条件恒为真」的短路在这个项目里已经实打实出现过两次(uploadDoneTexts 的 querySelector
 * 兜底把上传等待变成空操作、coverSelected 的泛选择器让封面永远不被选),两次都是**静默**的:
 * 判定照常返回 true,故障表现成完全无关的样子,查起来极贵。所以做成通用自检:一旦发现,大声记日志,
 * 并且**不再依据它重复点击**(拿一个坏判定去重复点击 = 重复投稿,代价比漏判大得多)。
 *
 * 这条自检是预防性的,不是为某次已知故障加的补丁 —— 当前四个平台的判定都通过自检。
 */
async function acceptancePreflight(
  what: string,
  accepted: () => Promise<boolean>,
): Promise<boolean> {
  const alreadyTrue = await accepted().catch(() => false);
  if (alreadyTrue) {
    plog(
      `${what}: 受理判定在点击前就为真 —— 它无法区分成功与失败,本次只点一次,结果交给 waitResult`,
    );
  }
  return alreadyTrue;
}

export async function commitClick(opts: {
  /** 这件事叫什么,用于日志与错误信息,如 `bilibili submit`。 */
  what: string;
  attempts: readonly ClickAttempt[];
  accepted: () => Promise<boolean>;
  /**
   * 点了但没反应时,记下当时的页面现场。
   *
   * 「元素找到了、可见、未禁用、落点也命中它,点下去却毫无反应」这种情况,光靠点击侧的信息是查不动的
   * ——真相在页面上(校验没过的提示、上传其实没完成、平台弹了别的东西)。而后台视图截不到图
   * (capturePage 对未参与合成的视图返回空图),所以只能靠文本快照。
   */
  snapshot?: () => Promise<unknown>;
}): Promise<string> {
  const tried: string[] = [];
  let clickedAny = false;
  // 判定坏了就不能再靠它决定「换下一种点法」——否则一个恒为真的判定会变成重复投稿的开关。
  const acceptanceBlind = await acceptancePreflight(opts.what, opts.accepted);
  for (const attempt of opts.attempts) {
    tried.push(attempt.label);
    const clicked = await attempt.click().then(
      () => true,
      (error: unknown) => {
        // 点不出去是常态而非异常:元素被遮挡、禁用、或视口无效时 PageDriver 会显式抛错,
        // 正是为了让这里能换下一种(而不是静默地假装点过了)。
        plog(`${opts.what}: attempt failed`, attempt.label, String(error).slice(0, 160));
        return false;
      },
    );
    if (!clicked) continue;
    clickedAny = true;
    plog(`${opts.what}: clicked`, attempt.label, `(${attempt.kind})`);
    if (acceptanceBlind) {
      // 判定不可信:点一次就收,别拿坏判定去重复投稿。成功与否交给 waitResult 判。
      plog(`${opts.what}: 判定不可信,点击已送达,后续交给结果等待`, attempt.label);
      return attempt.label;
    }
    if (await opts.accepted()) {
      plog(`${opts.what}: accepted`, attempt.label, `(${attempt.kind})`);
      return attempt.label;
    }
    plog(`${opts.what}: no reaction, trying next after`, attempt.label);
    if (opts.snapshot) {
      const state = await opts
        .snapshot()
        .catch((error: unknown) => ({ snapshotFailed: String(error).slice(0, 120) }));
      plog(`${opts.what}: page state`, JSON.stringify(state));
    }
  }
  throw new CommitClickError(opts.what, clickedAny, tried);
}
