import type { Locator, Page } from "@playwright/test";

type Frame = { x: number; y: number; width: number; height: number };

export type Scene = {
  id: number;
  caption: string;
  frame?: Frame;
  start: number[];
  end: number[];
};
export class Director {
  readonly scenes: Scene[] = [];
  readonly skipped: { id: number; reason: string }[] = [];
  private sequence = 0;
  private frame?: Frame;
  private position = { x: 360, y: 260 };
  constructor(readonly page: Page) {}

  skip(id: number, reason: string) {
    this.skipped.push({ id, reason });
  }
  async point(target: Locator) {
    await target.scrollIntoViewIfNeeded();
    const box = await target.boundingBox();
    if (!box) throw new Error("The selected control is not visible");
    const next = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    // Playwright recordings omit the system pointer. The overlays follow the same real mouse events.
    await this.page.evaluate(() => {
      if (document.getElementById("zu-recorder-pointer")) return;
      const pointer = document.createElement("div");
      pointer.id = "zu-recorder-pointer";
      Object.assign(pointer.style, {
        position: "fixed",
        left: "0",
        top: "0",
        width: "18px",
        height: "18px",
        border: "3px solid white",
        borderRadius: "50%",
        background: "#1f4d3f",
        boxShadow: "0 0 0 2px #1f4d3f",
        pointerEvents: "none",
        zIndex: "2147483646",
        transform: "translate(-80px,-80px)",
      });
      document.documentElement.append(pointer);
      document.addEventListener("mousemove", (e) => {
        pointer.style.transform =
          "translate(" + (e.clientX - 9) + "px," + (e.clientY - 9) + "px)";
      });
      document.addEventListener("mousedown", () => {
        pointer.animate(
          [
            { boxShadow: "0 0 0 2px #1f4d3f" },
            { boxShadow: "0 0 0 11px #f8c762cc", offset: 0.25 },
            { boxShadow: "0 0 0 18px #35825b66", offset: 0.65 },
            { boxShadow: "0 0 0 2px #1f4d3f" },
          ],
          650,
        );
      });
    });
    for (let i = 1; i <= 10; i++) {
      await this.page.mouse.move(
        this.position.x + ((next.x - this.position.x) * i) / 10,
        this.position.y + ((next.y - this.position.y) * i) / 10,
      );
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    this.position = next;
  }
  async click(target: Locator) {
    await this.point(target);
    await target.click({ timeout: 5000 });
  }
  async closeUp(target: Locator, width: number, offsetY = 0) {
    const bounds = await target.boundingBox();
    const screen = this.page.viewportSize();
    if (!bounds || !screen) throw new Error("Unable to frame the visible target.");
    const w = Math.min(screen.width, Math.ceil(width / 32) * 32);
    const h = w * 9 / 16;
    const origin = (center: number, size: number, limit: number) =>
      2 * Math.floor(Math.max(0, Math.min(center - size / 2, limit - size)) / 2);
    this.frame = {
      x: origin(bounds.x + bounds.width / 2, w, screen.width),
      y: origin(bounds.y + bounds.height / 2 + offsetY, h, screen.height),
      width: w, height: h,
    };
  }
  private async marker(rgb: number[]) {
    await this.page.evaluate((color) => {
      let bar = document.getElementById("zu-capture-sync");
      if (!bar) {
        bar = document.createElement("div");
        bar.id = "zu-capture-sync";
        document.documentElement.append(bar);
      }
      Object.assign(bar.style, {
        position: "fixed",
        bottom: "0",
        left: "0",
        width: "40px",
        height: "26px",
        zIndex: "2147483647",
        pointerEvents: "none",
        background: "rgb(" + color.join(",") + ")",
      });
    }, rgb);
    await this.page.waitForTimeout(320);
  }
  async step(
    id: number,
    caption: string,
    action: () => Promise<void>,
    holdMs = 2500,
  ): Promise<boolean> {
    const index = this.sequence++;
    this.frame = undefined;
    const colors = (n: number) => [
      42 + Math.floor(n / 16) * 70,
      32 + (Math.floor(n / 4) % 4) * 62,
      32 + (n % 4) * 62,
    ];
    const start = colors(index * 2),
      end = colors(index * 2 + 1);
    try {
      await this.marker(start);
      await action();
      await this.page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise<void>((r) =>
          requestAnimationFrame(() => requestAnimationFrame(() => r())),
        );
      });
      await this.page.waitForTimeout(holdMs);
      await this.marker(end);
      this.scenes.push({ id, caption, start, end, frame: this.frame });
      return true;
    } catch (err) {
      this.skip(
        id,
        err instanceof Error
          ? err.message.split("\n")[0].slice(0, 180)
          : "Action did not complete.",
      );
      return false;
    }
  }
}
