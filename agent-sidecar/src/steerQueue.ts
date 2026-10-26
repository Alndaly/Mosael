/**
 * 插话队列的账本,以及「整队重新声明」那一件事。
 *
 * pi 只能清空插话队列,不能删其中一条(见 Agent.clearSteeringQueue / steer)。界面上「删掉某条还没发的插话」
 * 于是只能靠「把剩下的整队再声明一遍」来表达(protocol.ts 的 QueueRequest)。可**重新声明就是重新入队**:
 *
 * - 模型已经读进上下文的某条又被声明一次 → 同一句话在模型眼里出现两遍,用户会看到它翻来覆去改同一件事;
 * - 已经出队、正在交给模型的某条又被声明一次 → 同样两遍。
 *
 * 所以每一轮记三样:见过、此刻还排着、已被模型读走。声明时把后两类挡在外面,重新声明才真的是幂等的。
 */
import type { Agent } from "@earendil-works/pi-agent-core";

import type { QueuedSteer } from "./protocol.js";

/** pi 上真正用到的两个动作:清空插话队列、排一条插话。 */
export type SteerTarget = Pick<Agent, "clearSteeringQueue" | "steer">;

/** 一轮对话的插话账本。轮次结束即丢(见 index.ts 的 finally)。 */
export class SteerLedger {
  private readonly seen = new Set<string>();
  private pending = new Set<string>();
  private readonly applied = new Set<string>();

  /** 这一轮里排进过队列。`pending=false` 用于 follow_up:它不在插话队列里。 */
  recordQueued(steerId: string, pending = true): void {
    this.seen.add(steerId);
    if (pending) this.pending.add(steerId);
  }

  /** 模型真的把这条读进上下文了(pi 的 message_start,见 pi.ts)。 */
  recordApplied(steerId: string): void {
    this.pending.delete(steerId);
    this.applied.add(steerId);
  }

  /** 把「应该还排着的」落实成 pi 队列里的内容,返回**真的排上了**的那几条。 */
  declare(target: SteerTarget, items: QueuedSteer[]): QueuedSteer[] {
    const keep: QueuedSteer[] = [];
    for (const item of items) {
      // 模型已经读过这条:再排一次,同一句话就会在上下文里出现两遍。
      if (this.applied.has(item.steerId)) continue;
      // 见过、却已不在队列里:pi 刚把它取走(正在交给模型的路上)—— 再排一次同样是两遍。
      if (this.seen.has(item.steerId) && !this.pending.has(item.steerId)) continue;
      keep.push(item);
    }
    target.clearSteeringQueue();
    for (const item of keep) {
      target.steer({
        role: "user",
        content: item.prompt,
        timestamp: Date.now(),
        // 带上 Mosael 的消息 id:模型读到它时 sidecar 才能回传 steer_applied,
        // 后端据此把这条移出队列。丢了 id,它就永远「还没被消费」,下一轮会被再执行一遍。
        ...(item.steerId ? { mosaelSteerId: item.steerId } : {}),
      });
      this.seen.add(item.steerId);
    }
    this.pending = new Set(keep.map((item) => item.steerId));
    return keep;
  }
}
