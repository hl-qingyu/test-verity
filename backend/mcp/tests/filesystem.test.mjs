import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, mkdir, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";

test("upstream server reads full Unicode input and refuses outside paths and writes", async () => {
  const folder = await mkdtemp(join(tmpdir(), "verity-filesystem-"));
  const allowed = join(folder, "allowed");
  await mkdir(allowed);
  const path = join(allowed, "input.json");
  const original = JSON.stringify({
    text: "中文完整原文🌱\n".repeat(100000),
    end: "EOF_SENTINEL",
  });
  await writeFile(path, original, "utf8");
  await writeFile(join(folder, "private.txt"), "SYNTHETIC_PRIVATE", "utf8");
  const client = new Client({
    name: "verity-filesystem-test",
    version: "1.0.0",
  });
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [
      fileURLToPath(
        new URL(
          "../node_modules/@modelcontextprotocol/server-filesystem/dist/index.js",
          import.meta.url,
        ),
      ),
      "--read-only",
      "--confine-roots",
      allowed,
    ],
    cwd: allowed,
    stderr: "pipe",
  });
  try {
    await client.connect(transport);
    const tools = (await client.listTools()).tools;
    assert.ok(tools.some((t) => t.name === "read_text_file"));
    assert.ok(tools.every((t) => t.annotations?.readOnlyHint === true));
    assert.ok(
      !tools.some((t) =>
        ["write_file", "edit_file", "move_file", "create_directory"].includes(
          t.name,
        ),
      ),
    );
    const response = await client.callTool({
      name: "read_text_file",
      arguments: { path },
    });
    assert.ok(!response.isError);
    const text = response.content.find((c) => c.type === "text").text;
    assert.equal(text, original);
    assert.equal(
      createHash("sha256").update(text).digest("hex"),
      createHash("sha256").update(original).digest("hex"),
    );
    const outside = await client.callTool({
      name: "read_text_file",
      arguments: { path: join(folder, "private.txt") },
    });
    assert.equal(outside.isError, true);
    assert.ok(!JSON.stringify(outside).includes("SYNTHETIC_PRIVATE"));
    const write = await client
      .callTool({
        name: "write_file",
        arguments: { path, content: "overwrite" },
      })
      .catch((error) => ({ isError: true, error }));
    assert.equal(write.isError, true);
    assert.equal(await readFile(path, "utf8"), original);
  } finally {
    await client.close();
    await rm(folder, { recursive: true, force: true });
  }
});
