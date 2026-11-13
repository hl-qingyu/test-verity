// Skill management prototype: fixed local content, browser-only revisions.
let skSelected = "requirement-analysis",
  skPath = "SKILL.md",
  skMode = "read",
  skDraft = null;
const skExpanded = new Set(["examples", "scripts"]);
function skRecord(key = skSelected) {
  return SKILL_CONTENT.find((s) => s.key === key);
}
function skRevision(key = skSelected) {
  return S.skillManagement?.[key] || { revision: 0 };
}
function skFile(path = skPath) {
  return skRecord()?.files.find((f) => f.path === path);
}
function skText(file = skFile()) {
  return file?.path === "SKILL.md"
    ? (skRevision().text ?? file.text)
    : (file?.text ?? "");
}
function skParts(text) {
  const prefix = text.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n*/)?.[0] || "";
  return { prefix, body: text.slice(prefix.length) };
}
function skDirty() {
  return !!skDraft && skDraft.body !== skDraft.original;
}
function skMarkdown(text) {
  return window
    .renderVerityMarkdown(text, "sk-" + skSelected)
    .replaceAll('data-action="doc-link"', 'data-action="sk-link"')
    .replace(/<small class="hint">[\s\S]*?<\/small>/g, "");
}
function skUsage(file) {
  return file.usage === "current"
    ? "参与当前AI调用"
    : file.path === "legacy-contract.md"
      ? "历史约定"
      : "参考文件";
}
function skPurpose(file) {
  return (
    {
      "SKILL.md": "分析说明",
      "contract.md": "输出约定",
      "evaluation.md": "评估说明",
      "legacy-contract.md": "旧版输出约定",
      "resources.json": "调用文件清单",
    }[file.path] ||
    (file.path.startsWith("examples/")
      ? "合成示例"
      : file.path.startsWith("scripts/")
        ? "校验脚本 · 只读源码"
        : "参考资料")
  );
}
function skFileButton(file) {
  return `<button type="button" class="sk-file ${file.path === skPath ? "selected" : ""}" data-action="sk-file" data-id="${esc(file.path)}" ${file.path === skPath ? 'aria-current="true"' : ""}><span class="sk-file-icon" aria-hidden="true">${icon(file.path.endsWith(".md") ? "file" : "code")}</span><span><strong>${esc(file.path.split("/").at(-1))}</strong><small>${esc(skPurpose(file))}</small></span></button>`;
}
function skTree(prefix = "") {
  const files = skRecord().files,
    children = [
      ...new Set(
        files
          .filter((f) => f.path.startsWith(prefix))
          .map((f) => f.path.slice(prefix.length).split("/")[0]),
      ),
    ];
  children.sort(
    (a, b) =>
      (({ "SKILL.md": -2, "contract.md": -1 })[a] ?? 0) -
        ({ "SKILL.md": -2, "contract.md": -1 }[b] ?? 0) || a.localeCompare(b),
  );
  return children
    .map((name) => {
      const path = prefix + name,
        file = files.find((f) => f.path === path);
      if (file) return skFileButton(file);
      return `<details class="sk-folder" data-sk-folder="${esc(path)}" ${skExpanded.has(path) ? "open" : ""}><summary><span>${icon("file")}</span>${esc(name)}/</summary><div class="sk-folder-children">${skTree(path + "/")}</div></details>`;
    })
    .join("");
}
function skContent() {
  const file = skFile(),
    text = skText(file);
  if (!file) return empty("文件暂不可用", "请重新选择文件。");
  if (file.path.endsWith(".md") && skMode === "read")
    return skMarkdown(skParts(text).body);
  let shown = text;
  if (file.path.endsWith(".json") && skMode === "read") {
    try {
      shown = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return (
        note("JSON格式无法解析，以下保留原文。", true) +
        `<pre class="sk-code">${esc(text)}</pre>`
      );
    }
  }
  return `<pre class="sk-code">${esc(shown)}</pre>`;
}
function viewSkills() {
  const record = skRecord(),
    file = skFile(),
    revision = skRevision(),
    modeLabel = file.path.endsWith(".json") ? "格式化" : "阅读";
  return (
    header("Skill 管理", "查看分析方法与完整文件内容，所有项目共用。") +
    `<p class="hint sk-demo-note">原型演示 · 文件来自项目Skill的固定快照；修改仅保存在当前浏览器，不修改项目文件或正式分析。</p><div class="sk-layout">
    <nav class="panel sk-list" aria-label="Skill列表"><div class="panel-head"><h2>分析 Skill</h2><span class="hint">5项</span></div><div class="sk-list-body">${SKILL_CONTENT.map((s) => `<button type="button" class="sk-item ${s.key === skSelected ? "selected" : ""}" data-action="sk-select" data-id="${s.key}" ${s.key === skSelected ? 'aria-current="true"' : ""}><span class="tile-icon">${icon(s.icon)}</span><span><strong>${esc(s.name)}</strong><small>v${esc(s.version)} · ${s.files.length}个文件</small></span></button>`).join("")}</div><p class="hint sk-list-foot">${admin() ? "平台管理员可修改分析说明正文" : "当前角色只读，修改需平台管理员"}</p></nav>
    <section class="panel sk-files"><details class="sk-tree-shell" open><summary>文件目录 <span class="hint">${record.files.length}个文件</span></summary><div class="sk-tree-root">${skTree()}</div></details></section>
    <section class="panel sk-reader"><div class="sk-reader-head"><div class="sk-reader-title"><p class="eyebrow">${esc(record.name)}</p><h2 tabindex="-1" id="skFileTitle">${esc(file.path)}</h2><div class="row">${tag(skPurpose(file))}${tag(skUsage(file), skUsage(file) === "参与当前AI调用" ? "green" : "")}</div><p class="hint">底版 ${esc(record.version)} · 修订 ${revision.revision} · ${revision.revision ? "浏览器演示修订" : "项目文件快照"}${revision.time ? " · " + esc(revision.actor) + " · " + esc(revision.time) : ""}</p></div>${admin() && file.path === "SKILL.md" ? btn(icon("edit") + "修改内容", "sk-edit", "", "primary") : ""}</div>
    <div class="sk-reader-toolbar"><div class="tabs" aria-label="文件展示方式">${file.path.endsWith(".md") || file.path.endsWith(".json") ? `<button type="button" data-action="sk-mode" data-id="read" class="${skMode === "read" ? "selected" : ""}" aria-pressed="${skMode === "read"}">${modeLabel}</button>` : ""}<button type="button" data-action="sk-mode" data-id="raw" class="${skMode === "raw" || !/\.(md|json)$/.test(file.path) ? "selected" : ""}" aria-pressed="${skMode === "raw" || !/\.(md|json)$/.test(file.path)}">原文</button></div><span class="hint">${file.path.startsWith("scripts/") ? "仅展示，不执行" : file.path.startsWith("examples/") ? "合成示例，不是业务报告" : file.path === "SKILL.md" ? "方法说明" : "只读文件"}</span></div><article class="sk-content" id="skFileContent">${skContent()}</article></section></div>`
  );
}
function skSelectFile(path, focus = true) {
  if (!skRecord().files.some((f) => f.path === path))
    return toast("此文件不在当前Skill展示范围内");
  skPath = path;
  skMode = "read";
  const parts = path.split("/");
  for (let i = 1; i < parts.length; i++)
    skExpanded.add(parts.slice(0, i).join("/"));
  render();
  if (focus)
    document.getElementById("skFileTitle")?.focus({ preventScroll: true });
}
function skResolveLink(from, href) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|\\)/i.test(href)) return null;
  let clean;
  try {
    clean = decodeURIComponent(href.split(/[?#]/)[0]);
  } catch {
    return null;
  }
  if (clean.includes("\\") || clean.includes("\0")) return null;
  const parts = from.split("/").slice(0, -1);
  for (const piece of clean.split("/")) {
    if (!piece || piece === ".") continue;
    if (piece === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else parts.push(piece);
  }
  const path = clean ? parts.join("/") : from;
  return skRecord().files.some((f) => f.path === path) ? path : null;
}
function skEditOpen() {
  if (!admin() || skPath !== "SKILL.md")
    return toast("仅平台管理员可修改分析说明");
  const parts = skParts(skText());
  skDraft = {
    key: skSelected,
    prefix: parts.prefix,
    original: parts.body,
    body: parts.body,
    revision: skRevision().revision,
    tab: "editor",
    busy: false,
    assistant: false,
    question: "",
    references: [],
    aiBusy: false,
    candidate: null,
  };
  for (const turn of skChat(skDraft))
    if (turn.status === "pending") turn.status = "cancelled";
  skEditRender();
  document.getElementById("skEditor")?.focus();
}
function skEditRender(state = "editor") {
  const d = skDraft;
  if (!d) return;
  modalContext = { type: "sk-editor", state };
  const record = skRecord(d.key),
    confirm = state !== "editor";
  const body = confirm
    ? `<p>${state === "discard" ? "正文有未保存的修改，确定放弃吗？" : "确认保存「" + esc(record.name) + "」的分析说明？"}</p><p class="hint mt">${state === "discard" ? "放弃后保留原内容。" : "正式功能将影响所有项目的新分析；已准备、执行中和历史分析保持原内容。本次仅保存浏览器演示修订。"}</p>`
    : `<p class="hint">${esc(record.name)} / SKILL.md · 修订 ${d.revision} · 仅修改正文，元信息及输出契约保持只读。</p><div class="sk-edit-toolbar"><div class="tabs"><button type="button" data-action="sk-edit-tab" data-id="editor" class="${d.tab === "editor" ? "selected" : ""}">编辑正文</button><button type="button" data-action="sk-edit-tab" data-id="preview" class="${d.tab === "preview" ? "selected" : ""}">预览</button></div><button type="button" class="ghost small" data-action="sk-ai-toggle" aria-expanded="${d.assistant}">${icon("spark")}${d.assistant ? "收起AI辅助修改" : "AI辅助修改"}</button></div><div class="sk-edit-workspace ${d.assistant ? "with-assistant" : ""}"><section class="sk-manual-editor">${d.tab === "editor" ? `<form id="skEditForm"><label class="field-label">Markdown正文<textarea id="skEditor" name="body" rows="16" spellcheck="false" maxlength="200000" ${d.aiBusy ? "disabled" : ""}>${esc(d.body)}</textarea></label></form>` : `<article class="sk-edit-preview">${skMarkdown(d.body)}</article>`}${d.candidate ? skDiffView(d.candidate) : ""}</section>${d.assistant ? skChatView(d) : ""}</div><p class="hint mt">预览和AI建议均不代表保存。应用到草稿后，仍需管理员确认保存。</p>`;
  const footer =
    state === "discard"
      ? btn("继续编辑", "sk-edit-back") +
        btn("放弃修改", "sk-discard", "", "danger")
      : state === "save"
        ? btn("返回编辑", "sk-edit-back") +
          `<button type="button" class="primary" data-action="sk-save" ${d.busy ? "disabled" : ""}>${d.busy ? "保存演示修订中…" : "确认保存（演示）"}</button>`
        : btn("取消", "close") +
          `<button type="button" id="skSaveButton" class="primary" data-action="sk-save-confirm" ${!skDirty() || !d.body.trim() || d.aiBusy ? "disabled" : ""}>保存修改</button>`;
  openModal(
    state === "discard"
      ? "放弃修改"
      : state === "save"
        ? "保存确认"
        : "修改 Skill 内容",
    body,
    footer,
    !confirm,
  );
  document.getElementById("dialog").classList.add("sk-edit-dialog");
  document
    .getElementById("dialog")
    .classList.toggle("sk-ai-dialog", !confirm && d.assistant);
  if (d.busy)
    document
      .querySelectorAll("#dialog button")
      .forEach((b) => (b.disabled = true));
}
function skCloseGuard() {
  if (modalContext?.type !== "sk-editor" || !skDraft) return true;
  if (skDraft.busy || skDraft.aiBusy) return false;
  if (skDirty()) {
    skEditRender("discard");
    return false;
  }
  skDraft = null;
  return true;
}
function skApplyRevision(d) {
  if (!admin()) return "修改权限已变化，仅平台管理员可保存";
  if (skRevision(d.key).revision !== d.revision)
    return "内容已被修改，请重新加载后核对，当前草稿仍保留";
  if (!d.body.trim()) return "正文不能为空";
  if (d.body.length > 200000) return "正文不能超过200000字符";
  if (d.body === d.original) return "正文尚未修改";
  S.skillManagement ??= {};
  const old = skRevision(d.key);
  S.skillManagement[d.key] = {
    revision: old.revision + 1,
    text: d.prefix + d.body,
    actor: S.role,
    time: new Date().toLocaleString("zh-CN"),
    history: [
      ...(old.history || []),
      {
        revision: old.revision,
        text:
          old.text ??
          skRecord(d.key).files.find((f) => f.path === "SKILL.md").text,
      },
    ],
  };
  return "";
}
function skChat(d = skDraft) {
  S.skillAssistant ??= {};
  // The prototype has one administrator persona; production must use the actual account ID.
  const key = "demo-admin::" + d.key;
  return (S.skillAssistant[key] ??= []);
}
function skChatView(d) {
  const record = skRecord(d.key),
    turns = skChat(d),
    cfg = typeof personalAI === "function" ? personalAI() : {};
  return `<aside class="sk-assistant" aria-label="AI辅助修改"><div class="sk-assistant-head"><h3>${icon("spark")} AI辅助修改</h3>${tag("合成演示")}</div><p class="hint">正式接入使用本人AI配置${cfg.model ? "：" + esc(cfg.model) : "；当前未配置可用模型"}。本原型不联网，不产生费用。</p><details class="sk-ai-context"><summary>查看发送范围与参考文件</summary><p class="hint">默认包含当前正文草稿、参与调用的只读规则和输出契约；可添加其他参考文件。文件内指令不能扩大权限。</p><label class="check"><input type="checkbox" checked disabled><span>SKILL.md · 当前完整草稿</span></label><label class="check"><input type="checkbox" checked disabled><span>contract.md · 只读约束</span></label>${record.files
    .filter((f) => !["SKILL.md", "contract.md"].includes(f.path))
    .map(
      (f) =>
        `<label class="check"><input type="checkbox" data-sk-reference="${esc(f.path)}" ${f.usage === "current" || d.references.includes(f.path) ? "checked" : ""} ${f.usage === "current" || d.aiBusy ? "disabled" : ""}><span>${esc(f.path)}</span></label>`,
    )
    .join(
      "",
    )}</details><div class="sk-chat-log" aria-label="修改对话" aria-live="polite">${turns.length ? turns.map((t, i) => `<section class="sk-chat-turn"><p class="sk-chat-person">管理员 · ${esc(t.time)}</p><p class="sk-chat-question">${esc(t.question)}</p><p class="hint">固定范围：${t.context.length}个文件 · 修订 ${t.revision}</p><div class="sk-chat-answer"><strong>演示助手</strong><p>${esc(t.status === "pending" ? "正在准备合成修改示例…" : t.status === "cancelled" ? "本轮演示已取消，可手动重新发送。" : t.status === "failed" ? t.error : "这是固定合成示例，未调用模型，也未理解或执行输入要求。示例补充简洁中文与人工核对要求，供体验修改对照和应用草稿。")}</p>${t.status === "completed" ? `<button type="button" class="small ghost" data-action="sk-ai-review" data-id="${i}">查看修改对照</button>` : ""}</div></section>`).join("") : '<div class="sk-chat-empty">描述你想如何调整分析方法。<br>建议先体验：让说明更简洁，保留证据与权限边界。</div>'}</div><form id="skAIForm"><label class="field-label">修改要求<textarea id="skAIQuestion" rows="3" maxlength="4000" ${d.aiBusy ? "disabled" : ""} placeholder="例如：说明写得更简洁，保留必要的证据与人工核对要求">${esc(d.question)}</textarea></label><div class="sk-ai-actions"><span class="hint">Ctrl / ⌘ + Enter 发送</span>${d.aiBusy ? btn("取消本轮演示", "sk-ai-cancel", "", "small") : `<button type="button" id="skAISend" class="primary small" data-action="sk-ai-send" ${!d.question.trim() ? "disabled" : ""}>发送（演示）</button>`}</div></form><p class="hint">按当前管理员与Skill保留浏览器演示对话；应用只修改草稿，保存另行确认。</p></aside>`;
}
function skChanged(before, after) {
  let start = 0,
    end = 0;
  while (
    start < Math.min(before.length, after.length) &&
    before[start] === after[start]
  )
    start++;
  while (
    end < Math.min(before.length, after.length) - start &&
    before.at(-end - 1) === after.at(-end - 1)
  )
    end++;
  return {
    removed: before.slice(start, end ? -end : undefined),
    added: after.slice(start, end ? -end : undefined),
  };
}
function skDiffView(c) {
  const diff = skChanged(c.before, c.after),
    stale = skDraft.body !== c.before,
    done = c.applied || c.dismissed;
  return `<section class="sk-ai-diff" aria-label="AI修改对照"><div class="between"><h3>修改对照</h3>${tag(c.applied ? "已应用到草稿，尚未保存" : c.dismissed ? "已放弃此建议" : "建议待核对", c.applied ? "green" : "")}</div><p class="hint">${c.applied ? "可继续编辑，点击底部保存后才生成演示修订。" : stale ? "当前草稿已变化，不能覆盖。请按最新草稿重新发送修改要求。" : "这是固定合成正文补充；输出契约、元信息和脚本保持原文。"}</p><div class="sk-diff-columns"><section><h4>修改前 · 变化部分</h4><pre>${esc(diff.removed || "无删除，仅新增内容")}</pre><details><summary>查看完整修改前正文</summary><pre>${esc(c.before)}</pre></details></section><section><h4>修改后 · 变化部分</h4><pre>${esc(diff.added || "无新增内容")}</pre><details><summary>查看完整建议正文</summary><pre>${esc(c.after)}</pre></details></section></div>${!done ? `<div class="row mt"><button type="button" class="primary small" data-action="sk-ai-apply" ${stale || skDraft.aiBusy ? "disabled" : ""}>应用到草稿</button>${btn("放弃此建议", "sk-ai-dismiss", "", "ghost small")}</div>` : ""}</section>`;
}
function skAISend(d) {
  if (!admin()) return error("仅平台管理员可使用AI辅助修改");
  if (d.aiBusy || d.busy) return;
  if (!d.question.trim() || d.question.length > 4000)
    return error("请输入1至4000字符的修改要求");
  if (d.body.length > 200000) return error("请先缩小正文，最多200000字符");
  if (skRevision(d.key).revision !== d.revision)
    return error("Skill已被其他修改更新，请重新加载后再讨论；草稿仍保留");
  const record = skRecord(d.key);
  const context = [
    { path: "SKILL.md", text: d.prefix + d.body },
    ...record.files
      .filter((f) => f.path !== "SKILL.md" && (f.usage === "current" || d.references.includes(f.path)))
      .map((f) => ({ path: f.path, text: f.text })),
  ];
  const turn = {
    question: d.question.trim(),
    before: d.body,
    context,
    revision: d.revision,
    status: "pending",
    time: new Date().toLocaleString("zh-CN"),
  };
  skChat(d).push(turn);
  d.question = "";
  d.aiBusy = true;
  d.pending = turn;
  save();
  skEditRender();
  setTimeout(() => {
    if (skDraft !== d || d.pending !== turn || turn.status !== "pending")
      return;
    d.aiBusy = false;
    d.pending = null;
    if (!admin() || skRevision(d.key).revision !== d.revision) {
      turn.status = "failed";
      turn.error =
        "权限或Skill修订已变化，本轮未生成可应用建议。草稿与历史对话保留。";
    } else {
      const addition =
        "\n\n## 说明表达补充（原型合成示例）\n\n- 使用简洁中文，先说明问题，再说明影响和建议。\n- 保留来源依据与关键条件，不把证据不足写成已证明。\n- 结果由人工核对，修改分析方法不能扩大平台操作权限。\n";
      turn.status = "completed";
      turn.after = turn.before + addition;
      d.candidate = {
        before: turn.before,
        after: turn.after,
        revision: turn.revision,
        applied: false,
        dismissed: false,
      };
    }
    save();
    skEditRender();
    document.querySelector(".sk-chat-log")?.scrollTo({ top: 1e7 });
  }, 700);
}
function skAIAction(action, id) {
  const d = skDraft;
  if (!d || !admin()) return toast("仅平台管理员可使用AI辅助修改");
  if (d.busy || (d.aiBusy && action !== "sk-ai-cancel")) return;
  if (action === "sk-ai-toggle") {
    d.assistant = !d.assistant;
    skEditRender();
    if (d.assistant) document.getElementById("skAIQuestion")?.focus();
  }
  if (action === "sk-ai-send") skAISend(d);
  if (action === "sk-ai-cancel" && d.pending) {
    d.pending.status = "cancelled";
    d.question = d.pending.question;
    d.pending = null;
    d.aiBusy = false;
    save();
    skEditRender();
  }
  if (action === "sk-ai-review") {
    const turn = skChat(d)[Number(id)];
    if (turn?.status !== "completed") return;
    d.candidate = {
      before: turn.before,
      after: turn.after,
      revision: turn.revision,
      applied: false,
      dismissed: false,
    };
    skEditRender();
    document.querySelector(".sk-ai-diff")?.scrollIntoView({ block: "nearest" });
  }
  if (action === "sk-ai-dismiss" && d.candidate) {
    d.candidate.dismissed = true;
    skEditRender();
  }
  if (action === "sk-ai-apply") {
    const c = d.candidate;
    if (!c || c.applied || c.dismissed) return;
    if (
      d.body !== c.before ||
      skRevision(d.key).revision !== c.revision ||
      d.revision !== c.revision
    )
      return error("草稿或Skill版本已变化，不能覆盖；请重新发送修改要求");
    if (!c.after.trim() || c.after.length > 200000)
      return error("建议正文为空或过长，未应用");
    d.body = c.after;
    c.applied = true;
    d.tab = "editor";
    skEditRender();
    toast("已应用到草稿，尚未保存Skill");
  }
}
function skAction(action, id) {
  if (action.startsWith("sk-ai-")) {
    skAIAction(action, id);
    return;
  }
  if (action === "sk-select") {
    if (!skRecord(id)) return;
    skSelected = id;
    skPath = "SKILL.md";
    skMode = "read";
    render();
    document
      .querySelector(`[data-action="sk-select"][data-id="${id}"]`)
      ?.focus({ preventScroll: true });
  }
  if (action === "sk-file") skSelectFile(id);
  if (action === "sk-mode") {
    skMode = id === "raw" ? "raw" : "read";
    render();
    document
      .querySelector(`[data-action="sk-mode"][data-id="${skMode}"]`)
      ?.focus({ preventScroll: true });
  }
  if (action === "sk-link") {
    let href;
    try {
      href = JSON.parse(id)[1];
    } catch {
      return;
    }
    const target = skResolveLink(skPath, href);
    if (!target)
      return toast("链接目标未纳入当前Skill文件范围，原型不会访问外部地址");
    if (skDraft) return toast("请结束正文编辑后再查看引用文件");
    skSelectFile(target);
  }
  if (action === "sk-edit") skEditOpen();
  if (action === "sk-edit-tab") {
    if (!skDraft) return;
    skDraft.tab = id;
    skEditRender();
    document
      .querySelector(`[data-action="sk-edit-tab"][data-id="${id}"]`)
      ?.focus();
  }
  if (action === "sk-save-confirm") {
    if (!skDraft || !admin()) return error("仅平台管理员可保存");
    if (skDraft.aiBusy) return;
    if (!skDirty() || !skDraft.body.trim()) return error("请填写有修改的正文");
    skEditRender("save");
  }
  if (action === "sk-edit-back") skEditRender();
  if (action === "sk-discard") {
    const next = skDraft?.next;
    skDraft = null;
    closeModal();
    render();
    if (next) navigate(next);
    else document.querySelector('[data-action="sk-edit"]')?.focus();
  }
  if (action === "sk-save") {
    const d = skDraft;
    if (!d || d.busy || d.aiBusy) return;
    d.busy = true;
    skEditRender("save");
    setTimeout(() => {
      if (skDraft !== d) return;
      d.busy = false;
      const message = skApplyRevision(d);
      if (message) {
        skEditRender();
        error(message);
        return;
      }
      skDraft = null;
      save();
      closeModal();
      render();
      document.querySelector('[data-action="sk-edit"]')?.focus();
      toast("演示修订已保存，仅在当前浏览器生效；正式Skill未修改");
    }, 450);
  }
}
document.addEventListener(
  "click",
  (event) => {
    const button = event.target.closest("[data-action]");
    if (!button?.dataset.action.startsWith("sk-")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    skAction(button.dataset.action, button.dataset.id || "");
  },
  true,
);
document.addEventListener("input", (event) => {
  if (event.target.id === "skAIQuestion" && skDraft) {
    skDraft.question = event.target.value;
    const send = document.getElementById("skAISend");
    if (send) send.disabled = !skDraft.question.trim() || skDraft.aiBusy;
    return;
  }
  if (event.target.id !== "skEditor" || !skDraft) return;
  skDraft.body = event.target.value;
  const button = document.getElementById("skSaveButton");
  if (button)
    button.disabled = !skDirty() || !skDraft.body.trim() || skDraft.aiBusy;
});
document.addEventListener("change", (event) => {
  if (!event.target.dataset?.skReference || !skDraft || skDraft.aiBusy) return;
  const path = event.target.dataset.skReference;
  if (!skRecord(skDraft.key).files.some((f) => f.path === path)) return;
  skDraft.references = event.target.checked
    ? [...new Set([...skDraft.references, path])]
    : skDraft.references.filter((p) => p !== path);
});
document.addEventListener("keydown", (event) => {
  if (
    event.target.id === "skAIQuestion" &&
    event.key === "Enter" &&
    (event.ctrlKey || event.metaKey)
  ) {
    event.preventDefault();
    skAIAction("sk-ai-send", "");
  }
});
document.addEventListener(
  "toggle",
  (event) => {
    const path = event.target.dataset?.skFolder;
    if (!path) return;
    event.target.open ? skExpanded.add(path) : skExpanded.delete(path);
  },
  true,
);
document.addEventListener("keydown", (event) => {
  if (
    !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) ||
    !event.target.closest(".sk-tree-root,.sk-list-body")
  )
    return;
  const root = event.target.closest(".sk-tree-root,.sk-list-body"),
    items = [...root.querySelectorAll("button,summary")].filter(
      (x) => x.getClientRects().length,
    );
  const index = items.indexOf(event.target);
  if (index < 0) return;
  event.preventDefault();
  items[
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : (index + (event.key === "ArrowUp" ? -1 : 1) + items.length) %
          items.length
  ]?.focus();
});
window.addEventListener("beforeunload", (event) => {
  if (skDirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
// End Skill management prototype.
