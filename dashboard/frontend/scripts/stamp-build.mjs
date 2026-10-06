import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { posix } from "node:path";
const { join } = posix;
async function files(dir) {
  return (
    await Promise.all(
      (await readdir(dir, { withFileTypes: true })).map((e) =>
        e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
      ),
    )
  ).flat();
}
const paths = [
  ...(await files("src")),
  ...(await files("public")),
  "index.html",
  "package.json",
  "package-lock.json",
  "tsconfig.json",
  "vite.config.ts",
  "scripts/stamp-build.mjs",
].sort();
const hash = createHash("sha256");
for (const path of paths) {
  hash.update(path + "\0");
  hash.update(await readFile(path));
}
const source_sha256 = hash.digest("hex");
if (process.argv.includes("--check")) {
  const current = JSON.parse(
    await readFile("dist/build-manifest.json", "utf8"),
  );
  if (current.source_sha256 !== source_sha256)
    throw new Error("前端源码已变化，请运行 npm run build 并提交 dist");
  console.log("Prebuilt frontend matches source.");
} else
  await writeFile(
    "dist/build-manifest.json",
    JSON.stringify({ source_sha256 }, null, 2) + "\n",
  );
