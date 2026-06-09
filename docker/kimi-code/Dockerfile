FROM node:24-bookworm-slim

ARG KIMI_CODE_VERSION=0.11.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@moonshot-ai/kimi-code@${KIMI_CODE_VERSION}"

RUN node - <<'NODE'
const fs = require("node:fs");
const path = "/usr/local/lib/node_modules/@moonshot-ai/kimi-code/dist/main.mjs";
const text = fs.readFileSync(path, "utf8");
const needle = "\nmain();\nasync function logStartupFailure";
if (!text.includes(needle)) {
  throw new Error("Could not find kimi-code main() call to guard");
}
fs.writeFileSync(
  path,
  text.replace(
    needle,
    '\nif (process.env.KIMI_CODE_SKIP_AUTO_MAIN !== "1") main();\nasync function logStartupFailure',
  ),
);
NODE

COPY run-agent /opt/harness/run-agent
RUN chmod +x /opt/harness/run-agent

ENV HOME=/kimi-home
WORKDIR /workspace
