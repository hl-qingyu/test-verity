"""Embed approved Skill file-viewing prototype into each total HTML in place."""

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
MODULES = [
    ("requirement-analysis", "需求分析", "3.0.2", "spark"),
    ("case-generation", "用例生成", "2.1.2", "list"),
    ("case-analysis", "用例分析", "1.0.1", "chart"),
    ("code-review", "代码分析", "2.0.1", "code"),
    ("change-impact", "变更分析", "1.0.4", "branch"),
]
data = []
for key, name, version, icon in MODULES:
    folder = ROOT / "skill" / key
    manifest = folder / "resources.json"
    current = json.loads(manifest.read_text(encoding="utf-8"))["instructions"] if manifest.exists() else ["SKILL.md", "contract.md"]
    files = []
    for file in sorted(folder.rglob("*")):
        if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
            continue
        assert file.resolve().is_relative_to(folder.resolve())
        text = file.read_bytes().decode("utf-8")
        files.append({"path": file.relative_to(folder).as_posix(), "text": text,
                      "sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "usage": "current" if file.relative_to(folder).as_posix() in current else "reference"})
    data.append({"key": key, "name": name, "version": version, "icon": icon, "files": files})

serialized = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
block = "// Skill management content snapshot.\nconst SKILL_CONTENT = " + serialized + ";\n" + (SOURCE / "skill-management.js").read_text(encoding="utf-8").rstrip("\n")
style = '<style id="skill-management-layout">\n' + (SOURCE / "skill-management.css").read_text(encoding="utf-8") + "\n</style>\n"
for arg in sys.argv[1:]:
    target = Path(arg).resolve()
    assert target.name in {"verity-prototype.html", "verity-requirement-risk-review.html"}
    assert target == (ROOT / "verity-prototype.html").resolve() or target == (ROOT / "docs/prototypes/verity-requirement-risk-review.html").resolve()
    original = target.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    html = original.replace("\r\n", "\n")
    kind = "repo" if target.is_relative_to(ROOT) else "external"
    backup = ROOT / f"outputs/prototype-pending/verity-prototype.{kind}-before-skill-ai-chat-20261014.html"
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    if "// Skill management content snapshot." in html:
        start = html.index("// Skill management content snapshot.")
        end = html.index("// End Skill management prototype.", start) + len("// End Skill management prototype.")
        html = html[:start] + block + html[end:]
    else:
        html, count = re.subn(r"^function viewSkills\(\).*\n", lambda _: block + "\n", html, count=1, flags=re.M)
        assert count == 1
        start = html.index("function editSkill(")
        end = html.index("// Local code is prototype-only:", start)
        html = html[:start] + html[end:]
        start = html.index("case'edit-skill':")
        end = html.index("case'remove-repo':", start)
        html = html[:start] + html[end:]
        html = html.replace("function closeModal(){", "function closeModal(){if(!skCloseGuard())return;", 1)
        html = html.replace("function navigate(key){", "function navigate(key){if(skDraft){skDraft.next=key;if(!skCloseGuard())return;closeModal();}", 1)
        html = html.replace("'cg-review-dialog');d.classList.toggle", "'cg-review-dialog','sk-edit-dialog');d.classList.toggle", 1)
        old = "document.getElementById('dialog').addEventListener('cancel',e=>{if(e.target!==e.currentTarget)"
        new = "document.getElementById('dialog').addEventListener('cancel',e=>{if(modalContext?.type==='sk-editor'){e.preventDefault();if(skCloseGuard())closeModal();return;}if(e.target!==e.currentTarget)"
        assert old in html
        html = html.replace(old, new, 1)
        old = "window.addEventListener('hashchange',()=>{page=location.hash.slice(1)||'overview';"
        new = "window.addEventListener('hashchange',()=>{if(skDraft){skDraft.next=location.hash.slice(1)||'overview';if(!skCloseGuard()){history.replaceState(null,'','#'+page);return;}closeModal();}page=location.hash.slice(1)||'overview';"
        assert old in html
        html = html.replace(old, new, 1)
    style_pattern = r'<style id="skill-management-layout">[\s\S]*?</style>'
    if re.search(style_pattern, html):
        html = re.sub(style_pattern, lambda _: style.rstrip("\n"), html, count=1)
    else:
        html = html.replace("</head>", style + "</head>", 1)
    html = html.replace("'sk-edit-dialog');d.classList.toggle", "'sk-edit-dialog','sk-ai-dialog');d.classList.toggle", 1)
    assert html.count("function viewSkills()") == 1
    assert "case'publish-skill'" not in html
    target.write_bytes(html.replace("\n", newline).encode("utf-8"))
    print(f"Updated {kind} total prototype; {sum(len(s['files']) for s in data)} fixed source files.")
