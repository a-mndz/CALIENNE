import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { MAX_MESSAGE_CHARS } from "../src/constants/input.js";


test("message limit is shared and enforced at input boundary", async () => {
  const input = await readFile(new URL("../src/components/ChatInputBar.jsx", import.meta.url), "utf8");
  const dashboard = await readFile(new URL("../src/CalienneDashboard.jsx", import.meta.url), "utf8");

  assert.equal(MAX_MESSAGE_CHARS, 4000);
  assert.match(input, /maxLength=\{MAX_MESSAGE_CHARS\}/);
  assert.match(dashboard, /finalText\.length > MAX_MESSAGE_CHARS/);
});


test("unsupported execution controls are absent", async () => {
  const input = await readFile(new URL("../src/components/ChatInputBar.jsx", import.meta.url), "utf8");

  for (const unsupported of ["Web Search", "Attach", "Manual", "Auto-Expand Reasoning"]) {
    assert.equal(input.includes(unsupported), false, unsupported);
  }
});


test("development server proxies authenticated backend routes", async () => {
  const config = await readFile(new URL("../vite.config.js", import.meta.url), "utf8");

  assert.match(config, /'\/api': 'http:\/\/localhost:8000'/);
  assert.match(config, /'\/auth': 'http:\/\/localhost:8000'/);
});


test("content security policy is enforced in index.html", async () => {
  const html = await readFile(new URL("../index.html", import.meta.url), "utf8");

  assert.match(html, /http-equiv="Content-Security-Policy"/);
  assert.match(html, /default-src 'self'/);
  assert.match(html, /connect-src 'self'/);
});


test("human-in-the-loop pause and resume contracts are wired", async () => {
  const dashboard = await readFile(new URL("../src/CalienneDashboard.jsx", import.meta.url), "utf8");
  const thread = await readFile(new URL("../src/components/ChatThread.jsx", import.meta.url), "utf8");

  assert.match(dashboard, /eventType === "node_paused"/);
  assert.match(dashboard, /\/api\/runs\/\$\{encodeURIComponent\(traceId\)\}\/resume/);
  assert.match(dashboard, /onResume=\{handleResumeRun\}/);
  assert.match(thread, /HitlClarificationCard/);
  assert.match(thread, /m\.role === "paused"/);
});


test("dynamic insights bind verification telemetry to RightPanel", async () => {
  const dashboard = await readFile(new URL("../src/CalienneDashboard.jsx", import.meta.url), "utf8");
  const panel = await readFile(new URL("../src/components/RightPanel.jsx", import.meta.url), "utf8");

  assert.match(dashboard, /insights=\{liveInsights\}/);
  assert.match(dashboard, /resData\.consensus_score/);
  assert.match(panel, /insights = INSIGHTS/);
});

