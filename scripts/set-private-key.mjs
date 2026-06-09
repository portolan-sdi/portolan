import { readFileSync } from "fs";
import { execFileSync } from "child_process";

const keyPath = process.argv[2];
const pem = readFileSync(keyPath, "utf8");

// Store as a single line with literal \n escapes. Multiline values get
// truncated at the first newline by `vercel env add --value`, and pull
// round-trips them inconsistently. The route normalizes \n back to newlines.
const oneLine = pem.replace(/\r?\n/g, "\\n");

execFileSync(
  "vercel",
  [
    "env",
    "add",
    "GITHUB_PRIVATE_KEY",
    "production",
    `--value=${oneLine}`,
    "--no-sensitive",
    "--force",
  ],
  { stdio: ["inherit", "pipe", "pipe"] }
);
console.log("ok");
