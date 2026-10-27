/**
 * **挡路的浮层**:平台的提示框、新手引导、必须确认的弹窗。
 *
 * 这一类问题在 2026-10-23 一天里让发布失败了三次(可见范围设不上、正文没进去、入口点不到),
 * 而每次的形状都一样:**平台弹了个东西,我们没关,它把下一步挡住了** —— 而且页面不会报错,
 * 失败以"某个无关的步骤超时"的形式出现。各适配器此前各写一套 `dismissHints` / `dismissOnboarding`,
 * 谁漏写谁就中招。
 *
 * 这里收成一份**声明**:每种浮层写清「怎么认出它」和「怎么关掉它」,关法由驱动层的原语执行。
 * 规则放在 `selectors.ts`(那里本来就是"平台页面长什么样"的词表),由执行器在每一步之前统一跑一遍。
 */
import { plog } from "../log";

/** 关浮层要用到的驱动原语 —— 只声明用得到的几个,测试里好替身。 */
export interface OverlayDriver {
  hasText(text: string): Promise<boolean>;
  cssVisible(selector: string, timeout?: number): Promise<boolean>;
  clickCss(selector: string): Promise<void>;
  pressKey(key: "Enter" | "Escape" | "Space" | "Tab"): Promise<void>;
}

/** 「按文案点」由调用方给(各平台的可点元素范围不一样,见 shared 的 clickTextPreferTrusted)。 */
export type ClickByText = (text: string) => Promise<void>;

/**
 * 一种浮层。
 *
 * - `detect`:认它的依据 —— 页面文字,或一个选择器(新手引导那种没有固定文案的);
 * - `dismiss`:关它的动作,按顺序做:`tick`(先勾一个框)→ `clickSelector`(按选择器点,最准)→
 *   `click`(按文案点)→ `escape`(按 Esc);
 * - `gone`:关掉之后该消失的那句话,默认就是 `detect` 的文字(用选择器认的必须自己给)。
 */
export interface OverlayRule {
  /** 规则名:适配器要"确认某一条关掉了没有"时按它找,不用重复页面文案。 */
  id?: string;
  detect: { text?: string; selector?: string };
  dismiss: { tick?: string; clickSelector?: string; click?: string; escape?: boolean };
  gone?: { text?: string; selector?: string };
}

/** 关掉之后等它真的消失(过渡动画 / 异步卸载)。等不到就当没关掉。 */
async function waitGone(driver: OverlayDriver, rule: OverlayRule, timeout = 1_500): Promise<boolean> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (!(await stillThere(driver, rule))) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}

/** 最多找几轮。一轮里把每条规则试一次,关掉一个就重来 —— 有的弹窗是套着的。 */
const MAX_ROUNDS = 3;

async function present(driver: OverlayDriver, rule: OverlayRule): Promise<boolean> {
  if (rule.detect.text) {
    return driver.hasText(rule.detect.text).catch(() => false);
  }
  if (rule.detect.selector) {
    return driver.cssVisible(rule.detect.selector, 400).catch(() => false);
  }
  return false;
}

async function stillThere(driver: OverlayDriver, rule: OverlayRule): Promise<boolean> {
  const gone = rule.gone ?? rule.detect;
  if (gone.text) return driver.hasText(gone.text).catch(() => false);
  if (gone.selector) return driver.cssVisible(gone.selector, 400).catch(() => false);
  return false;
}

async function dismiss(driver: OverlayDriver, clickText: ClickByText, rule: OverlayRule): Promise<void> {
  const { tick, clickSelector, click, escape } = rule.dismiss;
  if (tick) {
    await driver.clickCss(tick).catch(() => undefined);
  }
  //: **优先按选择器点**。按文案点会先命中包着按钮的外层容器(小红书那个提示框里,
  //: `div.feature-guide__footer` 的文字也是「我知道了」),点容器什么都不会发生 —— 真机 2026-10-23
  //: 就是这样:日志里"关掉了"七次,提示框一次都没关。
  if (clickSelector) {
    await driver.clickCss(clickSelector).catch(() => undefined);
  }
  if (click) {
    await clickText(click).catch(() => undefined);
  }
  if (escape) {
    await driver.pressKey("Escape").catch(() => undefined);
  }
}

/**
 * 把当前页面上挂着的浮层逐个关掉,返回**关掉了哪几条**(给日志与测试看)。
 *
 * 幂等:没有浮层时一次驱动调用都不做(每条规则先 `detect`);有关掉的就重来一轮,
 * 因为"关掉一个之后又冒出另一个"是平台的常态(勾原创 → 权益弹窗 → 关掉 → 又提示"已声明")。
 */
export async function clearOverlays(
  driver: OverlayDriver,
  rules: readonly OverlayRule[],
  label = "",
  clickText: ClickByText = async () => undefined,
): Promise<string[]> {
  const cleared: string[] = [];
  if (!rules.length) return cleared;
  for (let round = 0; round < MAX_ROUNDS; round += 1) {
    let acted = false;
    for (const rule of rules) {
      if (!(await present(driver, rule))) continue;
      const name = rule.detect.text ?? rule.detect.selector ?? "";
      await dismiss(driver, clickText, rule);
      cleared.push(name);
      acted = true;
      //: 关掉之后**等它真的消失**(过渡 200–400ms),等到了才算关掉;等不到才记一笔。
      const gone = await waitGone(driver, rule);
      plog(`overlay ${gone ? "cleared" : "still up"}${label ? ` (${label})` : ""}:`, name);
      break; // 关掉一个就重开一轮:页面上可能换了另一个浮层
    }
    if (!acted) return cleared;
  }
  return cleared;
}
