/**
 * 工作台的会话:一个 ComfyUI 连接的内嵌视图开成工作台时,主进程这一侧的那一段(ADR 0038 §3)。
 *
 * - 视图亮着、停在这台 ComfyUI 上时,大约每 300ms 取一次桥(`poll`):选中的节点、有没有没存的改动、能力、事件队列;规整过
 *   (见 comfyWorkbench.parseWorkbenchPoll)才交给渲染层,内容没变、也没有新事件就不发;
 * - 桥不在(页面刚载入、刷新过)就重新注入;前端还没就绪就等下一拍;
 * - 视图收起(用户回到 Mosael、换去别的视图)就停,告诉渲染层会话结束了;
 * - 渲染层要做的事(填值、导出、保存、写标记)经这里交给桥:会话不在就不做。
 *
 * 不碰 Electron:驱动、「视图还亮着吗」、发给渲染层的口子都由调用方给(publishWorker),测试里换成假的。
 */
import type { PageDriver } from "./pageDriver";
import { comfyReady } from "./comfyEditor";
import {
  parseWorkbenchPoll,
  parseWorkbenchResult,
  workbenchCallScript,
  workbenchInstallScript,
  workbenchPollScript,
  type WorkbenchCall,
  type WorkbenchCallResult,
  type WorkbenchState,
} from "./comfyWorkbench";

/** 轮询的节奏(ADR 0038 §3:大约 300ms)。 */
export const POLL_MS = 300;
const POLL_BUDGET_MS = 2_000;
//: 导出一张大图、刷新下拉要重新拉一遍节点定义:都可能要几秒
const CALL_BUDGET_MS: Record<WorkbenchCall["op"], number> = {
  setWidget: 5_000,
  refreshCombos: 60_000,
  export: 60_000,
  save: 5_000,
  setMarks: 10_000,
  locate: 5_000,
};

type Driver = Pick<PageDriver, "evaluate">;

/** 发给渲染层的:这个分区的工作台现在什么样;`null` 是会话结束了(视图收起)。 */
export type WorkbenchEmit = (partition: string, state: WorkbenchState | null) => void;

interface Session {
  origin: string;
  timer: ReturnType<typeof setTimeout> | null;
  last: string;
  stopped: boolean;
}

export class WorkbenchSessions {
  private sessions = new Map<string, Session>();

  constructor(
    private readonly deps: {
      driver: (partition: string) => Driver | null;
      visible: (partition: string) => boolean;
      emit: WorkbenchEmit;
      schedule?: (callback: () => void, ms: number) => ReturnType<typeof setTimeout>;
    },
  ) {}

  /** 开一个(已经开着就换成新的来源、接着轮询)。先注入桥,再开始轮询。 */
  start(partition: string, origin: string): void {
    this.stop(partition, false);
    const session: Session = { origin, timer: null, last: "", stopped: false };
    this.sessions.set(partition, session);
    void this.tick(partition, session);
  }

  /** 停(视图收起、开成了普通的编辑器)。`announce`:告诉渲染层会话结束了。 */
  stop(partition: string, announce = true): void {
    const session = this.sessions.get(partition);
    if (!session) return;
    session.stopped = true;
    if (session.timer) clearTimeout(session.timer);
    this.sessions.delete(partition);
    if (announce) this.deps.emit(partition, null);
  }

  active(partition: string): boolean {
    return this.sessions.has(partition);
  }

  /** 注入桥(页面就绪了才注入;就绪的判据和「在编辑器里打开」同一个)。回注入的结果。 */
  async install(partition: string): Promise<string> {
    const session = this.sessions.get(partition);
    const driver = this.deps.driver(partition);
    if (!session || !driver) return "closed";
    const ready = await driver.evaluate<boolean>(`!!(${comfyReady(session.origin)})`, POLL_BUDGET_MS).catch(() => false);
    if (!ready) return "notReady";
    return driver.evaluate<string>(workbenchInstallScript(session.origin), POLL_BUDGET_MS).catch(() => "failed");
  }

  /** 渲染层要做的一件事。会话不在、桥不在都说清楚,不做。 */
  async call(partition: string, call: WorkbenchCall): Promise<WorkbenchCallResult> {
    const session = this.sessions.get(partition);
    const driver = this.deps.driver(partition);
    if (!session || !driver) return { ok: false, error: "closed" };
    try {
      const raw = await driver.evaluate<unknown>(workbenchCallScript(session.origin, call), CALL_BUDGET_MS[call.op]);
      return parseWorkbenchResult(call, raw);
    } catch (error) {
      return { ok: false, error: "failed", message: String((error as Error)?.message ?? error).slice(0, 500) };
    }
  }

  private async tick(partition: string, session: Session): Promise<void> {
    if (session.stopped) return;
    if (!this.deps.visible(partition)) {
      this.stop(partition);
      return;
    }
    const driver = this.deps.driver(partition);
    if (driver) {
      const raw = await driver.evaluate<unknown>(workbenchPollScript(session.origin), POLL_BUDGET_MS).catch(() => null);
      if (session.stopped) return;
      const missing = Boolean(raw && typeof raw === "object" && (raw as { error?: unknown }).error === "missing");
      if (missing) await this.install(partition);
      const state = missing ? null : parseWorkbenchPoll(raw);
      if (state && !session.stopped) {
        const { events, ...rest } = state;
        const key = JSON.stringify(rest);
        if (key !== session.last || events.length > 0) {
          session.last = key;
          this.deps.emit(partition, state);
        }
      }
    }
    if (session.stopped) return;
    const next = () => void this.tick(partition, session);
    session.timer = this.deps.schedule ? this.deps.schedule(next, POLL_MS) : setTimeout(next, POLL_MS);
  }
}
