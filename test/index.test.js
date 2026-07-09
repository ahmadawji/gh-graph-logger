const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("crypto");
const { buildEncryptedLogEntry, buildHookBlock, createEntryId } = require("../index");

function decryptLogEntry(entry, secret) {
  const [, , ivEncoded, tagEncoded, ciphertextEncoded] = entry.split(":");
  const key = crypto.createHash("sha256").update(secret).digest();
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, Buffer.from(ivEncoded, "base64url"));
  decipher.setAuthTag(Buffer.from(tagEncoded, "base64url"));
  const decrypted = Buffer.concat([
    decipher.update(Buffer.from(ciphertextEncoded, "base64url")),
    decipher.final()
  ]);
  return JSON.parse(decrypted.toString("utf8"));
}

test("buildHookBlock installs background sync command", () => {
  const block = buildHookBlock();
  assert.match(block, /gh-graph-logger:managed:start/);
  assert.match(block, /\(gh-graph-logger sync >\/dev\/null 2>&1 &\)/);
  assert.match(block, /gh-graph-logger:managed:end/);
});

test("buildEncryptedLogEntry encrypts and preserves commit details", () => {
  const secret = "test-secret";
  const payload = {
    commitHash: "abc123",
    commitMessage: "feat: add private sync",
    sourceRepo: "my-repo",
    timestamp: "2026-01-01T00:00:00.000Z",
    secret
  };
  const encrypted = buildEncryptedLogEntry(payload);

  assert.ok(encrypted.startsWith("enc:v1:"));
  assert.ok(!encrypted.includes(payload.commitMessage));

  const decrypted = decryptLogEntry(encrypted, secret);
  assert.equal(decrypted.commitHash, payload.commitHash);
  assert.equal(decrypted.commitMessage, payload.commitMessage);
  assert.equal(decrypted.sourceRepo, payload.sourceRepo);
  assert.equal(decrypted.timestamp, payload.timestamp);
});

test("createEntryId is deterministic for a commit hash", () => {
  const hash = "8b8ed31d6fcf7f65a45f1ec17f2c02f3de14f2e2";
  assert.equal(createEntryId(hash), createEntryId(hash));
  assert.equal(createEntryId(hash).length, 12);
});
