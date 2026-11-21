import type { Locator, Page } from "@playwright/test";

export type Scene = {
  id: number;
  caption: string;
  start: number[];
  end: number[];
};
export class Director {
  readonly scenes: Scene[] = [];
  readonly skipped: { id: number; reason: string }[] = [];
  private sequence = 0;
  private position = { x: 360, y: 260 };
  constructor(readonly page: Page) {}

  skip(id: number, reason: string) {
    this.skipped.push({ id, reason });
  }
  async click(target: Locator) {
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
            { boxShadow: "0 0 0 18px #74b59866" },
            { boxShadow: "0 0 0 2px #1f4d3f" },
          ],
          480,
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
    await target.click({ timeout: 5000 });
  }
  async highlight(target: Locator) {
    await target.scrollIntoViewIfNeeded();
    await target.evaluate((el) => {
      el.setAttribute("data-zu-recording-highlight", "");
      const sheet = document.createElement("style");
      sheet.textContent =
        "[data-zu-recording-highlight]{outline:4px solid #35825b!important;outline-offset:5px!important}";
      document.head.append(sheet);
    });
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
      this.scenes.push({ id, caption, start, end });
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
