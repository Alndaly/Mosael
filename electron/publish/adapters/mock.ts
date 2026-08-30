import type { PublishTask } from "../types";
import type { PageDriver } from "../pageDriver";
import type { PublishAdapter } from "./shared";
import { escapeHtml, wait } from "./shared";

export class MockAdapter implements PublishAdapter {
  constructor(
    private readonly driver: PageDriver,
    private readonly task: PublishTask,
  ) {}

  async openCreatorPage(): Promise<void> {
    await this.driver.setHtml(`
      <main style="font-family: system-ui; padding: 32px;">
        <h1>Open Studio Mock Publisher</h1>
        <p>Task: ${escapeHtml(this.task.title)}</p>
        <p id="status">Status: preparing</p>
      </main>
    `);
    await wait(500);
  }

  async checkLogin(): Promise<boolean> {
    await wait(300);
    return true;
  }

  async uploadVideo(videoPath: string): Promise<void> {
    await this.status(`selected video: ${videoPath}`);
    await wait(700);
  }

  async fillTitle(title: string): Promise<void> {
    await this.status(`filled title: ${title}`);
    await wait(400);
  }

  async fillTags(tags: string[]): Promise<void> {
    await this.status(`filled tags: ${tags.join(", ") || "none"}`);
    await wait(400);
  }

  async submit(): Promise<void> {
    await this.status("submitted");
    await wait(500);
  }

  async waitResult(): Promise<void> {
    await this.status("publish success");
    await wait(500);
  }

  private async status(message: string): Promise<void> {
    await this.driver.evaluate(
      `(() => { const n = document.getElementById('status'); if (n) n.textContent = ${JSON.stringify(
        `Status: ${message}`,
      )}; })()`,
    );
  }
}
