import { cp, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../node_modules/pdfjs-dist/", import.meta.url);
const output = new URL("../public/pdfjs/", import.meta.url);
await mkdir(output, { recursive: true });
await Promise.all(
  ["cmaps", "standard_fonts", "wasm", "iccs", "LICENSE"].map((name) =>
    cp(
      fileURLToPath(new URL(name, root)),
      fileURLToPath(new URL(name, output)),
      { recursive: true },
    ),
  ),
);
const assetDirectory = new URL("../public/assets/", import.meta.url);
await mkdir(assetDirectory, { recursive: true });
await cp(
  new URL("../node_modules/@fontsource-variable/inter/LICENSE", import.meta.url),
  new URL("inter-license.txt", assetDirectory),
);
