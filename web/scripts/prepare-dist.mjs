import { cp, rm } from "node:fs/promises";
import { resolve } from "node:path";

const source = resolve("out");
const destination = resolve("dist");

await rm(destination, { recursive: true, force: true });
await cp(source, destination, { recursive: true });
