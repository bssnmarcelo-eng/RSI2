import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const metadataDirectory = resolve("dist", ".openai");
await mkdir(metadataDirectory, { recursive: true });
await copyFile(resolve(".openai", "hosting.json"), resolve(metadataDirectory, "hosting.json"));
