#!/usr/bin/env node

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { execFileSync } = require("child_process");

const CONFIG = {
  token: "gh-graph-logger.githubToken",
  username: "gh-graph-logger.githubUsername",
  targetRepo: "gh-graph-logger.targetRepo"
};

function runGit(args, options = {}) {
  return execFileSync("git", args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    ...options
  }).trim();
}

function ensureGitRepository(cwd) {
  runGit(["rev-parse", "--is-inside-work-tree"], { cwd });
}

function getGitDir(cwd) {
  return runGit(["rev-parse", "--git-dir"], { cwd });
}

function getConfig(key, { cwd, global = false } = {}) {
  try {
    const args = ["config"];
    if (global) args.push("--global");
    args.push("--get", key);
    return runGit(args, cwd ? { cwd } : {});
  } catch {
    return "";
  }
}

function setConfig(key, value, { cwd, global = false } = {}) {
  const args = ["config"];
  if (global) args.push("--global");
  args.push(key, value);
  runGit(args, cwd ? { cwd } : {});
}

function askQuestion(rl, question) {
  return new Promise((resolve) => {
    rl.question(question, (answer) => resolve(answer.trim()));
  });
}

function buildHookBlock() {
  return [
    "# gh-graph-logger:managed:start",
    "(gh-graph-logger sync >/dev/null 2>&1 &) ",
    "# gh-graph-logger:managed:end"
  ].join("\n");
}

function installOrUpdatePrePushHook(cwd) {
  const gitDir = getGitDir(cwd);
  const hookPath = path.resolve(cwd, gitDir, "hooks", "pre-push");
  const managedStart = "# gh-graph-logger:managed:start";
  const managedEnd = "# gh-graph-logger:managed:end";
  const block = buildHookBlock();

  let content = "";
  if (fs.existsSync(hookPath)) {
    content = fs.readFileSync(hookPath, "utf8");
  }

  if (!content.trim()) {
    content = "#!/bin/sh\n\n";
  } else if (!content.startsWith("#!")) {
    content = `#!/bin/sh\n\n${content}`;
  }

  const blockRegex = new RegExp(`${managedStart}[\\s\\S]*?${managedEnd}`);
  if (blockRegex.test(content)) {
    content = content.replace(blockRegex, block);
  } else {
    content = `${content.replace(/\s*$/, "")}\n\n${block}\n`;
  }

  fs.writeFileSync(hookPath, content, { mode: 0o755 });
  fs.chmodSync(hookPath, 0o755);
}

function buildEncryptedLogEntry({ commitHash, commitMessage, sourceRepo, timestamp, secret }) {
  const payload = JSON.stringify({
    commitHash,
    commitMessage: commitMessage.replace(/\s+/g, " ").trim(),
    sourceRepo,
    timestamp
  });
  const key = crypto.createHash("sha256").update(secret).digest();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([cipher.update(payload, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `enc:v1:${iv.toString("base64url")}:${tag.toString("base64url")}:${ciphertext.toString("base64url")}`;
}

function createEntryId(commitHash) {
  return crypto.createHash("sha256").update(commitHash).digest("hex").slice(0, 12);
}

async function githubRequest(url, token, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: "Bearer " + token,
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });

  if (!response.ok) {
    const errorText = await response.text();
    const error = new Error(`GitHub API error (${response.status})`);
    error.status = response.status;
    error.responseBody = errorText;
    throw error;
  }

  return response.status === 204 ? null : response.json();
}

async function initCommand() {
  const cwd = process.cwd();
  ensureGitRepository(cwd);

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  try {
    console.log("Let's configure your GitHub connection.\n");

    const token = await askQuestion(rl, "GitHub Personal Access Token (PAT): ");
    const username = await askQuestion(rl, "GitHub Username: ");
    const targetRepo = await askQuestion(rl, "Target GitHub Repository: ");

    if (!token || !username || !targetRepo) {
      throw new Error("All fields are required.");
    }

    setConfig(CONFIG.token, token, { global: true });
    setConfig(CONFIG.username, username, { cwd });
    setConfig(CONFIG.targetRepo, targetRepo, { cwd });
    installOrUpdatePrePushHook(cwd);

    console.log("\n✅ Successfully installed pre-push hook and saved configuration!");
  } finally {
    rl.close();
  }
}

async function syncCommand() {
  const cwd = process.cwd();

  try {
    ensureGitRepository(cwd);
  } catch {
    return;
  }

  const token = getConfig(CONFIG.token, { global: true });
  const username = getConfig(CONFIG.username, { cwd });
  const targetRepo = getConfig(CONFIG.targetRepo, { cwd });
  if (!token || !username || !targetRepo) return;

  let commitHash = "";
  let commitMessage = "";
  try {
    commitHash = runGit(["log", "-1", "--pretty=format:%H"], { cwd });
    commitMessage = runGit(["log", "-1", "--pretty=format:%s"], { cwd });
  } catch {
    return;
  }

  const timestamp = new Date().toISOString();
  const sourceRepo = path.basename(cwd);
  const entryId = createEntryId(commitHash);
  const encrypted = buildEncryptedLogEntry({
    commitHash,
    commitMessage,
    sourceRepo,
    timestamp,
    secret: token
  });
  const line = `- ${timestamp} \`${entryId}\` ${encrypted}`;
  const readmeApi = `https://api.github.com/repos/${encodeURIComponent(username)}/${encodeURIComponent(targetRepo)}/contents/README.md`;

  let currentReadme = "# Commit Log\n";
  let currentSha = undefined;

  try {
    const readme = await githubRequest(readmeApi, token, { method: "GET" });
    currentReadme = Buffer.from(readme.content || "", "base64").toString("utf8");
    currentSha = readme.sha;
  } catch (error) {
    if (error.status !== 404) return;
  }

  if (currentReadme.includes(`\`${entryId}\``)) return;

  const updatedReadme = `${currentReadme.replace(/\s*$/, "")}\n${line}\n`;
  const payload = {
    message: `chore: log private commit ${entryId}`,
    content: Buffer.from(updatedReadme, "utf8").toString("base64")
  };
  if (currentSha) payload.sha = currentSha;

  try {
    await githubRequest(readmeApi, token, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  } catch {
    return;
  }
}

async function main() {
  const command = process.argv[2];

  if (command === "init") {
    await initCommand();
    return;
  }

  if (command === "sync") {
    await syncCommand();
    return;
  }

  console.log("Usage: gh-graph-logger <init|sync>");
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`gh-graph-logger failed: ${error.message}`);
    process.exit(1);
  });
}

module.exports = {
  buildEncryptedLogEntry,
  buildHookBlock,
  createEntryId
};
