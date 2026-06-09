FROM node:24-bookworm-slim

ARG OPENCLAW_VERSION=2026.6.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

RUN node - <<'NODE'
const fs = require("node:fs");
const path = require("node:path");
const dist = "/usr/local/lib/node_modules/openclaw/dist";
const file = fs.readdirSync(dist)
  .filter((entry) => entry.startsWith("register.agent-turn-") && entry.endsWith(".js"))
  .find((entry) => fs.readFileSync(path.join(dist, entry), "utf8").includes("Message body for the agent"));
if (!file) {
  throw new Error("Could not find OpenClaw agent command registrar");
}
const target = path.join(dist, file);
let text = fs.readFileSync(target, "utf8");
const optionNeedle = '.requiredOption("-m, --message <text>", "Message body for the agent").option("-t, --to <number>", "Recipient number in E.164 used to derive the session key")';
if (!text.includes(optionNeedle)) {
  throw new Error("Could not find OpenClaw message option");
}
text = text.replace(
  optionNeedle,
  '.option("-m, --message <text>", "Message body for the agent").option("--message-file <path>", "Read message body from file").option("-t, --to <number>", "Recipient number in E.164 used to derive the session key")',
);
const actionNeedle = ".action(async (opts) => {\n\t\tconst verboseLevel";
if (!text.includes(actionNeedle)) {
  throw new Error("Could not find OpenClaw agent action body");
}
text = text.replace(
  actionNeedle,
  '.action(async (opts) => {\n\t\tif (typeof opts.messageFile === "string" && opts.messageFile.trim()) {\n\t\t\tconst { readFileSync } = await import("node:fs");\n\t\t\topts.message = readFileSync(opts.messageFile, "utf8");\n\t\t}\n\t\tconst verboseLevel',
);
fs.writeFileSync(target, text);
NODE

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/openclaw-home
WORKDIR /workspace
