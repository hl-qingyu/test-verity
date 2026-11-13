import { callModeName, readSelectedAI } from './aiConfiguration';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useBlocker } from 'react-router-dom';
import type { User } from './Auth';
import { CaseDialog } from './CaseDialog';
import { Form } from './Form';
import { Icon } from './Icon';
import { MarkdownPreview } from './MarkdownPreview';
import {
  skillList,
  skillPackage,
  skillBundle,
  skillSave,
  skillHistory,
  skillSend,
  skillCancel,
  skillError,
  skillErrors,
  resolveSkillLink,
  skillDifference,
} from './skillApi';
import type {
  SkillSummary,
  SkillPackage,
  SkillFile,
  SkillContent,
  SkillBundle,
  SkillTurn,
  SkillChatInput,
} from './skillApi';
import './skills.css';

type Props = { user: User; onSessionEnd: () => void };
const purpose = (f: SkillFile) =>
  ({
    'SKILL.md': '分析说明',
    'contract.md': '输出约定',
    'evaluation.md': '评估说明',
    'legacy-contract.md': '旧版输出约定',
    'resources.json': '调用文件清单',
  })[f.path] ||
  (f.path.startsWith('examples/')
    ? '合成示例'
    : f.path.startsWith('references/') && f.usage === 'current'
      ? '分析规则'
      : f.path.startsWith('scripts/')
        ? '校验脚本 · 只读源码'
        : '参考资料');
const usage = (f: SkillFile) =>
  ({ current: '参与当前AI调用', reference: '参考文件', legacy: '历史约定' })[f.usage];

export function Skills(props: Props) {
  return <SkillWorkspace key={props.user.id} {...props} />;
}
function SkillWorkspace({ user, onSessionEnd }: Props) {
  const [items, setItems] = useState<SkillSummary[]>([]),
    [selected, setSelected] = useState('requirement-analysis'),
    [record, setRecord] = useState<SkillPackage | null>(null),
    [fileId, setFileId] = useState(''),
    [content, setContent] = useState<SkillContent | null>(null),
    [mode, setMode] = useState('read'),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [loading, setLoading] = useState(true),
    [fileLoading, setFileLoading] = useState(false),
    [reload, setReload] = useState(0),
    [editing, setEditing] = useState(false),
    [editChecking, setEditChecking] = useState(false),
    [validation, setValidation] = useState(0),
    [expanded, setExpanded] = useState(new Set(['examples', 'scripts']));
  const editorButton = useRef<HTMLButtonElement>(null);
  const cache = useRef(new Map<string, { bundle: SkillBundle; checked: number }>()),
    currentFile = useRef(fileId),
    currentRecord = useRef(record),
    currentKey = useRef(selected),
    forceFresh = useRef(false),
    editLock = useRef(false),
    mounted = useRef(true);
  currentFile.current = fileId;
  currentRecord.current = record;
  currentKey.current = selected;
  useEffect(() => {
    const accountCache = cache.current;
    mounted.current = true;
    return () => {
      mounted.current = false;
      accountCache.clear();
    };
  }, []);
  const install = useCallback((p: SkillBundle, reset = false) => {
    const selectedFile =
      (!reset && p.files.find((f) => f.id === currentFile.current)) ||
      p.files.find((f) => f.path === 'SKILL.md');
    currentFile.current = selectedFile?.id || '';
    setRecord(p);
    setFileId(currentFile.current);
    setContent(p.contents.find((f) => f.id === currentFile.current) || null);
  }, []);
  useEffect(() => {
    if (user.platform_role !== 'ADMIN') setEditing(false);
  }, [user.platform_role]);
  useEffect(() => {
    const controller = new AbortController();
    skillList(controller.signal)
      .then(setItems)
      .catch((e) => {
        if (!controller.signal.aborted) setError(skillError(e, onSessionEnd));
      });
    return () => controller.abort();
  }, [onSessionEnd, reload]);
  useEffect(() => {
    if (editing) {
      setFileLoading(false);
      return;
    }
    const controller = new AbortController();
    const previous = cache.current.get(selected);
    if (previous) install(previous.bundle);
    setLoading(!previous && currentRecord.current?.key !== selected);
    setFileLoading(true);
    setError('');
    skillBundle(selected, previous?.bundle, controller.signal, forceFresh.current)
      .then((p) => {
        if (controller.signal.aborted) return;
        cache.current.set(selected, { bundle: p, checked: Date.now() });
        forceFresh.current = false;
        install(p);
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        cache.current.delete(selected);
        if (e instanceof Error && e.message === 'not_authenticated') {
          cache.current.clear();
          setRecord(null);
          setContent(null);
        }
        setError(skillError(e, onSessionEnd));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setFileLoading(false);
        }
      });
    return () => controller.abort();
  }, [selected, reload, validation, editing, install, onSessionEnd]);
  useEffect(() => {
    const verify = () => setValidation((n) => n + 1);
    window.addEventListener('focus', verify);
    return () => window.removeEventListener('focus', verify);
  }, []);
  function changeSkill(key: string) {
    setValidation((n) => n + 1);
    currentFile.current = '';
    setSelected(key);
    setMode('read');
    setNotice('');
    const saved = cache.current.get(key);
    if (saved) install(saved.bundle, true);
    else {
      setRecord(null);
      setContent(null);
      setFileId('');
      setLoading(true);
    }
  }
  async function openEditor() {
    if (!record || !content || editLock.current) return;
    editLock.current = true;
    setEditChecking(true);
    setError('');
    try {
      const latest = await skillPackage(record.key);
      if (
        !mounted.current ||
        currentKey.current !== record.key ||
        currentFile.current !== content.id
      )
        return;
      if (latest.token !== content.token) {
        cache.current.delete(record.key);
        forceFresh.current = true;
        setValidation((n) => n + 1);
        setNotice('文件已更新，已重新读取。请核对后再修改。');
        return;
      }
      setEditing(true);
    } catch (e) {
      if (mounted.current) setError(skillError(e, onSessionEnd));
    } finally {
      editLock.current = false;
      if (mounted.current) setEditChecking(false);
    }
  }
  const selectFile = useCallback(
    (f: SkillFile) => {
      const pieces = f.path.split('/');
      setExpanded((old) => {
        const next = new Set(old);
        for (let i = 1; i < pieces.length; i++) next.add(pieces.slice(0, i).join('/'));
        return next;
      });
      setFileId(f.id);
      currentFile.current = f.id;
      const saved = cache.current.get(selected);
      setContent(saved?.bundle.contents.find((c) => c.id === f.id) || null);
      setMode('read');
      if (!saved || Date.now() - saved.checked >= 5000) setValidation((n) => n + 1);
      setNotice('');
    },
    [selected],
  );
  function tree(prefix = ''): React.ReactNode {
    if (!record) return null;
    const children = [
      ...new Set(
        record.files
          .filter((f) => f.path.startsWith(prefix))
          .map((f) => f.path.slice(prefix.length).split('/')[0]),
      ),
    ];
    children.sort(
      (a, b) =>
        (({ 'SKILL.md': -2, 'contract.md': -1 })[a] ?? 0) -
          ({ 'SKILL.md': -2, 'contract.md': -1 }[b] ?? 0) || a.localeCompare(b),
    );
    return children.map((n) => {
      const path = prefix + n,
        f = record.files.find((f) => f.path === path);
      return f ? (
        <button
          type="button"
          className={`sk-file ${f.id === fileId ? 'selected' : ''}`}
          key={f.id}
          aria-current={f.id === fileId ? 'true' : undefined}
          onClick={() => selectFile(f)}
        >
          <span className="sk-file-icon">
            <Icon name={f.type === 'md' ? 'file' : 'code'} />
          </span>
          <span>
            <strong>{n}</strong>
            <small>{purpose(f)}</small>
          </span>
        </button>
      ) : (
        <details
          className="sk-folder"
          key={path}
          open={expanded.has(path)}
          onToggle={(e) => {
            const open = e.currentTarget.open;
            setExpanded((old) => {
              if (old.has(path) === open) return old;
              const next = new Set(old);
              if (open) next.add(path);
              else next.delete(path);
              return next;
            });
          }}
        >
          <summary>
            <Icon name="file" />
            {n}/
          </summary>
          <div className="sk-folder-children">{tree(path + '/')}</div>
        </details>
      );
    });
  }
  const preview = useMemo(() => {
    if (!content) return null;
    const link = (href: string) => {
      if (!record) return;
      const f = resolveSkillLink(content.path, href, record.files);
      if (f) selectFile(f);
      else setNotice('链接目标未纳入当前Skill文件范围，不会访问外部地址。');
    };
    if (content.type === 'unsupported') return <p className="hint">暂不支持预览此类型文件。</p>;
    if (mode === 'read' && content.type === 'md')
      return (
        <MarkdownPreview
          text={content.body}
          renderLink={(href, children) => (
            <button type="button" className="markdown-link-button" onClick={() => link(href)}>
              {children}
            </button>
          )}
        />
      );
    let text = content.text;
    if (mode === 'read' && content.type === 'json') {
      try {
        text = JSON.stringify(JSON.parse(text), null, 2);
      } catch {
        return (
          <>
            <p className="form-error">JSON格式无法解析，以下保留原文。</p>
            <pre className="sk-code">{text}</pre>
          </>
        );
      }
    }
    return <pre className="sk-code">{text}</pre>;
  }, [content, mode, record, selectFile]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Skill 管理</h1>
          <p>查看分析方法与完整文件内容，所有项目共用。</p>
        </div>
        <button
          type="button"
          disabled={loading || fileLoading}
          onClick={() => {
            cache.current.clear();
            forceFresh.current = true;
            setReload((n) => n + 1);
          }}
        >
          重新加载
        </button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="sk-layout">
        <nav className="panel sk-list" aria-label="Skill列表">
          <div className="panel-head">
            <h2>分析 Skill</h2>
            <span className="hint">{items.length}项</span>
          </div>
          <div className="sk-list-body" onKeyDown={treeKeys}>
            {items.map((s) => (
              <button
                type="button"
                key={s.key}
                className={`sk-item ${s.key === selected ? 'selected' : ''}`}
                aria-current={s.key === selected ? 'true' : undefined}
                onClick={() => changeSkill(s.key)}
              >
                <span className="tile-icon">
                  <Icon name={s.icon} />
                </span>
                <span>
                  <strong>{s.name}</strong>
                  <small>
                    v{s.version} · {s.file_count}个文件
                  </small>
                </span>
              </button>
            ))}
          </div>
          <p className="hint sk-list-foot">
            {user.platform_role === 'ADMIN'
              ? '平台管理员可修改分析说明正文'
              : '当前角色只读，修改需平台管理员'}
          </p>
        </nav>
        <section className="panel sk-files">
          <details className="sk-tree-shell" open>
            <summary>
              文件目录{' '}
              <span className="hint">{record ? `${record.file_count}个文件` : '读取中'}</span>
            </summary>
            <div className="sk-tree-root" onKeyDown={treeKeys}>
              {loading ? <p role="status">正在读取文件目录…</p> : tree()}
            </div>
          </details>
        </section>
        <section className="panel sk-reader">
          {record && content ? (
            <>
              <div className="sk-reader-head">
                <div className="sk-reader-title">
                  <p className="eyebrow">{record.name}</p>
                  <h2>{content.path}</h2>
                  <div className="row">
                    <span className="badge">{purpose(content)}</span>
                    <span className={`badge ${content.usage === 'current' ? 'green' : ''}`}>
                      {usage(content)}
                    </span>
                  </div>
                  <p className="hint">
                    底版 {record.version} · 内容 {content.sha256.slice(0, 8)} · 本地文件
                  </p>
                </div>
                {user.platform_role === 'ADMIN' && content.editable && (
                  <button
                    ref={editorButton}
                    type="button"
                    className="primary"
                    disabled={fileLoading || editChecking || !!error}
                    onClick={() => void openEditor()}
                  >
                    <Icon name="edit" />
                    {editChecking ? '正在核对…' : '修改内容'}
                  </button>
                )}
              </div>
              <div className="sk-reader-toolbar">
                <div className="tabs" aria-label="文件展示方式">
                  {['md', 'json'].includes(content.type) && (
                    <button
                      type="button"
                      className={mode === 'read' ? 'selected' : ''}
                      aria-pressed={mode === 'read'}
                      onClick={() => setMode('read')}
                    >
                      {content.type === 'json' ? '格式化' : '阅读'}
                    </button>
                  )}
                  <button
                    type="button"
                    className={
                      mode === 'raw' || !['md', 'json'].includes(content.type) ? 'selected' : ''
                    }
                    aria-pressed={mode === 'raw'}
                    onClick={() => setMode('raw')}
                  >
                    原文
                  </button>
                </div>
                <span className="hint">
                  {content.path.startsWith('scripts/')
                    ? '仅展示，不执行'
                    : content.path.startsWith('examples/')
                      ? '合成示例，不是业务报告'
                      : content.editable
                        ? '方法说明'
                        : '只读文件'}
                  {fileLoading ? ' · 正在核对文件…' : ''}
                </span>
              </div>
              <article className="sk-content">{preview}</article>
            </>
          ) : (
            <p className="panel-pad" role="status">
              {loading || fileLoading ? '正在读取文件内容…' : '请选择可读取的文件。'}
            </p>
          )}
        </section>
      </div>
      {editing && user.platform_role === 'ADMIN' && record && content && (
        <SkillEditor
          record={record}
          content={content}
          onSessionEnd={onSessionEnd}
          onClose={() => {
            setEditing(false);
            queueMicrotask(() => editorButton.current?.focus());
          }}
          onSaved={() => {
            cache.current.delete(selected);
            forceFresh.current = true;
            setEditing(false);
            setReload((n) => n + 1);
            setNotice('Skill文件已保存，旧文件已备份；已固定的分析任务保持原内容。');
          }}
        />
      )}
    </>
  );
}

function treeKeys(e: KeyboardEvent<HTMLElement>) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
  const items = [...e.currentTarget.querySelectorAll<HTMLElement>('button,summary')].filter(
      (x) => x.getClientRects().length,
    ),
    index = items.indexOf(e.target as HTMLElement);
  if (index < 0) return;
  e.preventDefault();
  items[
    e.key === 'Home'
      ? 0
      : e.key === 'End'
        ? items.length - 1
        : (index + (e.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
  ]?.focus();
}
type Candidate = {
  before: string;
  after: string;
  token: string;
  applied?: boolean;
  dismissed?: boolean;
};
function mergeTurns(old: SkillTurn[], items: SkillTurn[]) {
  const all = new Map(old.map((t) => [t.id, t]));
  items.forEach((t) => all.set(t.id, t));
  return [...all.values()].sort((a, b) => a.id - b.id);
}
export function SkillEditor({
  record,
  content,
  onSessionEnd,
  onClose,
  onSaved,
}: {
  record: SkillPackage;
  content: SkillContent;
  onSessionEnd: () => void;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [body, setBody] = useState(content.body),
    [tab, setTab] = useState('editor'),
    [assistant, setAssistant] = useState(false),
    [confirm, setConfirm] = useState<'save' | 'discard' | ''>(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [question, setQuestion] = useState(''),
    [refs, setRefs] = useState<string[]>([]),
    [history, setHistory] = useState<SkillTurn[]>([]),
    [more, setMore] = useState(false),
    [chatLoaded, setChatLoaded] = useState(false),
    [includeHistory, setIncludeHistory] = useState(true),
    [candidate, setCandidate] = useState<Candidate | null>(null),
    [ai, setAI] = useState('正在读取本人AI配置…');
  const alive = useRef(true),
    lock = useRef(false),
    saveId = useRef({ body: '', id: '' }),
    sendId = useRef<{ signature: string; payload: SkillChatInput } | null>(null);
  const dirty = body !== content.body,
    active = history.find((t) => t.status === 'QUEUED' || t.status === 'RUNNING');
  const blocker = useBlocker(dirty);
  const chatEpoch = useRef(0);
  const awaitedTurn = useRef(0);
  useEffect(() => {
    if (blocker.state === 'blocked') setConfirm('discard');
  }, [blocker.state]);
  const refreshChat = useCallback(async () => {
    const epoch = ++chatEpoch.current;
    const h = await skillHistory(record.key);
    if (alive.current && epoch === chatEpoch.current) {
      setHistory((old) => mergeTurns(old, h.items));
      setMore((old) => old || h.has_more);
      setChatLoaded(true);
      const completed = h.items.find((t) => t.id === awaitedTurn.current);
      if (completed?.status === 'COMPLETED') {
        setCandidate({
          before: completed.base_body,
          after: completed.candidate_body,
          token: completed.base_token,
        });
        awaitedTurn.current = 0;
      } else if (completed && ['FAILED', 'CANCELLED'].includes(completed.status))
        awaitedTurn.current = 0;
    }
  }, [record.key]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);
  useEffect(() => {
    if (!assistant) return;
    let stopped = false;
    const poll = async () => {
      try {
        await refreshChat();
      } catch (e) {
        if (!stopped) setError(skillError(e, onSessionEnd));
      }
    };
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 3000);
    readSelectedAI()
      .then((v) => {
        if (stopped) return;
        const personal = v && typeof v === 'object' && 'personal' in v ? v.personal : null;
        setAI(
          personal &&
            typeof personal === 'object' &&
            'model' in personal &&
            typeof personal.model === 'string'
            ? `${callModeName(personal.call_mode)} · ${personal.name} · ${personal.model}`
            : '请先在平台设置中配置本人AI服务',
        );
      })
      .catch((e) => {
        if (!stopped) setError(skillError(e, onSessionEnd));
      });
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [assistant, refreshChat, onSessionEnd]);
  function close() {
    if (busy || active) return;
    if (dirty) setConfirm('discard');
    else onClose();
  }
  async function save() {
    if (lock.current || active) return;
    lock.current = true;
    setBusy(true);
    setError('');
    if (saveId.current.body !== body) saveId.current = { body, id: crypto.randomUUID() };
    try {
      await skillSave(record.key, {
        request_id: saveId.current.id,
        expected_token: content.token,
        body,
      });
      if (alive.current) onSaved();
    } catch (e) {
      if (alive.current) setError(skillError(e, onSessionEnd));
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function send() {
    if (lock.current || active || !question.trim() || !chatLoaded) return;
    lock.current = true;
    setBusy(true);
    setError('');
    const signature = JSON.stringify({ body, question, refs, includeHistory });
    if (sendId.current?.signature !== signature)
      sendId.current = {
        signature,
        payload: {
          request_id: crypto.randomUUID(),
          expected_token: content.token,
          body,
          question,
          references: refs,
          last_turn_id: history.at(-1)?.id || 0,
          include_history: includeHistory,
        },
      };
    try {
      const turn = await skillSend(record.key, sendId.current.payload);
      if (!alive.current) return;
      chatEpoch.current++;
      awaitedTurn.current = turn.id;
      setHistory((old) => mergeTurns(old, [turn]));
      setQuestion('');
      sendId.current = null;
    } catch (e) {
      if (alive.current) {
        setError(skillError(e, onSessionEnd));
        if (e instanceof Error && e.message === 'skill_chat_history_changed') {
          sendId.current = null;
          void refreshChat().catch((e) => {
            if (alive.current) setError(skillError(e, onSessionEnd));
          });
        }
      }
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function cancel() {
    if (!active || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const turn = await skillCancel(record.key, active.id);
      if (alive.current) {
        chatEpoch.current++;
        awaitedTurn.current = 0;
        setHistory((old) => mergeTurns(old, [turn]));
      }
    } catch (e) {
      if (alive.current) setError(skillError(e, onSessionEnd));
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function earlier() {
    if (busy || !history.length) return;
    setBusy(true);
    try {
      const h = await skillHistory(record.key, history[0].id);
      if (alive.current) {
        setHistory((old) => mergeTurns(old, h.items));
        setMore(h.has_more);
      }
    } catch (e) {
      if (alive.current) setError(skillError(e, onSessionEnd));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function apply() {
    if (!candidate || candidate.applied || candidate.dismissed || lock.current || busy || active)
      return;
    if (body !== candidate.before || content.token !== candidate.token) {
      setError('草稿或Skill版本已变化，不能覆盖。请按当前草稿重新发送。');
      return;
    }
    lock.current = true;
    setBusy(true);
    setError('');
    try {
      const latest = await skillPackage(record.key);
      if (!alive.current) return;
      if (latest.token !== candidate.token) {
        setError('Skill文件已变化，未应用建议。请重新加载并核对。');
        return;
      }
      setBody(candidate.after);
      setCandidate({ ...candidate, applied: true });
      setTab('editor');
    } catch (e) {
      if (alive.current) setError(skillError(e, onSessionEnd));
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const diff = candidate ? skillDifference(candidate.before, candidate.after) : null;
  return (
    <CaseDialog
      title={
        confirm === 'save' ? '保存确认' : confirm === 'discard' ? '放弃修改' : '修改 Skill 内容'
      }
      wide={!confirm}
      busy={busy || !!active}
      onClose={close}
      className={`skills-editor sk-edit-dialog ${assistant && !confirm ? 'sk-ai-dialog' : ''}`}
      footer={
        <footer className="modal-footer">
          {confirm ? (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (blocker.state === 'blocked') blocker.reset();
                  setConfirm('');
                }}
              >
                继续编辑
              </button>
              <button
                type="button"
                className={confirm === 'discard' ? 'danger' : 'primary'}
                disabled={busy}
                onClick={() => {
                  if (confirm === 'discard') {
                    if (blocker.state === 'blocked') blocker.proceed();
                    onClose();
                  } else void save();
                }}
              >
                {busy ? '正在保存…' : confirm === 'discard' ? '放弃修改' : '确认保存'}
              </button>
            </>
          ) : (
            <>
              <button type="button" disabled={busy || !!active} onClick={close}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                disabled={!dirty || !body.trim() || busy || !!active || body.length > 200000}
                onClick={() => setConfirm('save')}
              >
                保存修改
              </button>
            </>
          )}
        </footer>
      }
    >
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {confirm ? (
        <>
          <p>
            {confirm === 'discard'
              ? '正文有未保存的修改，确定放弃吗？'
              : `确认保存「${record.name}」的分析说明？`}
          </p>
          <p className="hint">
            {confirm === 'discard'
              ? '对话历史仍保留，正文恢复到已保存文件。'
              : '保存将备份旧文件并写回本地SKILL.md，影响所有项目的新分析；已固定的任务保持原内容。'}
          </p>
        </>
      ) : (
        <>
          <p className="hint">
            {record.name} / SKILL.md · 内容 {content.sha256.slice(0, 8)} ·
            仅修改正文，元信息及输出契约只读。
          </p>
          <div className="sk-edit-toolbar">
            <div className="tabs">
              <button
                type="button"
                className={tab === 'editor' ? 'selected' : ''}
                onClick={() => setTab('editor')}
              >
                编辑正文
              </button>
              <button
                type="button"
                className={tab === 'preview' ? 'selected' : ''}
                onClick={() => setTab('preview')}
              >
                预览
              </button>
            </div>
            <button
              type="button"
              className="ghost small"
              aria-expanded={assistant}
              disabled={busy || !!active}
              onClick={() => setAssistant(!assistant)}
            >
              <Icon name="spark" />
              {assistant ? '收起AI辅助修改' : 'AI辅助修改'}
            </button>
          </div>
          <div className={`sk-edit-workspace ${assistant ? 'with-assistant' : ''}`}>
            <section className="sk-manual-editor">
              {tab === 'editor' ? (
                <Form onSubmit={(e) => e.preventDefault()}>
                  <label className="field-label">
                    Markdown正文
                    <textarea
                      id="skEditor"
                      rows={16}
                      spellCheck={false}
                      maxLength={200000}
                      required
                      disabled={busy || !!active}
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                    />
                  </label>
                </Form>
              ) : (
                <article className="sk-edit-preview">
                  <MarkdownPreview text={body} />
                </article>
              )}
              {candidate && diff && (
                <section className="sk-ai-diff" aria-label="AI修改对照">
                  <div className="between">
                    <h3>修改对照</h3>
                    <span className="badge">
                      {candidate.applied
                        ? '已应用到草稿，尚未保存'
                        : candidate.dismissed
                          ? '已放弃此建议'
                          : '建议待核对'}
                    </span>
                  </div>
                  <p className="hint">
                    {candidate.applied
                      ? '仍可人工编辑，保存后才修改Skill文件。'
                      : body !== candidate.before || content.token !== candidate.token
                        ? '当前草稿或文件版本已变化，不能覆盖，请重新发送。'
                        : '请核对变化，应用只修改草稿，保存另行确认。'}
                  </p>
                  <div className="sk-diff-columns">
                    <section>
                      <h4>修改前 · 变化部分</h4>
                      <pre>{diff.removed || '无删除，仅新增内容'}</pre>
                      <details>
                        <summary>查看完整修改前正文</summary>
                        <pre>{candidate.before}</pre>
                      </details>
                    </section>
                    <section>
                      <h4>修改后 · 变化部分</h4>
                      <pre>{diff.added || '无新增内容'}</pre>
                      <details>
                        <summary>查看完整建议正文</summary>
                        <pre>{candidate.after}</pre>
                      </details>
                    </section>
                  </div>
                  {!candidate.applied && !candidate.dismissed && (
                    <div className="row mt">
                      <button
                        type="button"
                        className="primary small"
                        disabled={
                          busy ||
                          !!active ||
                          body !== candidate.before ||
                          content.token !== candidate.token ||
                          candidate.after === body
                        }
                        onClick={apply}
                      >
                        应用到草稿
                      </button>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => setCandidate({ ...candidate, dismissed: true })}
                      >
                        放弃此建议
                      </button>
                    </div>
                  )}
                </section>
              )}
            </section>
            {assistant && (
              <aside className="sk-assistant" aria-label="AI辅助修改">
                <div className="sk-assistant-head">
                  <h3>
                    <Icon name="spark" />
                    AI辅助修改
                  </h3>
                  <span className="badge">本人AI</span>
                </div>
                <p className="hint">{ai}。发送将调用本人AI服务，可能产生费用。</p>
                <details className="sk-ai-context">
                  <summary>查看发送范围与参考文件</summary>
                  <p className="hint">
                    默认发送当前完整正文草稿、参与调用的只读规则和输出契约，可添加其他参考文件。
                  </p>
                  {record.files
                    .filter((f) => f.type !== 'unsupported')
                    .map((f) => (
                      <label className="check" key={f.id}>
                        <input
                          type="checkbox"
                          disabled={f.usage === 'current' || busy || !!active}
                          checked={f.usage === 'current' || refs.includes(f.id)}
                          onChange={(e) =>
                            setRefs((old) =>
                              e.target.checked ? [...old, f.id] : old.filter((id) => id !== f.id),
                            )
                          }
                        />
                        <span>{f.path}</span>
                      </label>
                    ))}
                  <label className="check">
                    <input
                      type="checkbox"
                      disabled={busy || !!active}
                      checked={includeHistory}
                      onChange={(e) => setIncludeHistory(e.target.checked)}
                    />
                    <span>携带已完成的历史对话</span>
                  </label>
                </details>
                <div className="sk-chat-log" aria-label="修改对话" aria-live="polite">
                  {more && (
                    <button
                      type="button"
                      className="small"
                      disabled={busy}
                      onClick={() => void earlier()}
                    >
                      加载更早对话
                    </button>
                  )}
                  {!chatLoaded ? (
                    <p role="status">正在读取对话…</p>
                  ) : !history.length ? (
                    <div className="sk-chat-empty">
                      描述你想如何调整分析方法。
                      <br />
                      例如：让说明更简洁，保留证据与权限边界。
                    </div>
                  ) : (
                    history.map((t) => (
                      <section className="sk-chat-turn" key={t.id}>
                        <p className="sk-chat-person">
                          管理员 · {new Date(t.created_at).toLocaleString('zh-CN')}
                        </p>
                        <p className="sk-chat-question">{t.question}</p>
                        <p className="hint">
                          固定范围：{t.references.join('、')} · {callModeName(t.ai.call_mode)} ·{' '}
                          {t.ai.name} · {t.ai.model}
                        </p>
                        <div className="sk-chat-answer">
                          <strong>AI助手</strong>
                          <p>
                            {t.status === 'COMPLETED'
                              ? t.answer
                              : t.status === 'QUEUED'
                                ? '已排队，等待后台执行…'
                                : t.status === 'RUNNING'
                                  ? '正在生成修改建议…'
                                  : t.status === 'CANCELLED'
                                    ? '本轮已取消，模型可能已处理并计费。'
                                    : skillErrors[t.error_code] ||
                                      '本轮失败，未修改文件。可核对后手动重新发送。'}
                          </p>
                          {t.status === 'COMPLETED' && (
                            <button
                              type="button"
                              className="small ghost"
                              onClick={() =>
                                setCandidate({
                                  before: t.base_body,
                                  after: t.candidate_body,
                                  token: t.base_token,
                                })
                              }
                            >
                              查看修改对照
                            </button>
                          )}
                        </div>
                      </section>
                    ))
                  )}
                </div>
                <Form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void send();
                  }}
                >
                  <label className="field-label">
                    修改要求
                    <textarea
                      id="skAIQuestion"
                      rows={3}
                      maxLength={4000}
                      required
                      disabled={busy || !!active}
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder="例如：说明写得更简洁，保留证据与人工核对要求"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                          e.preventDefault();
                          void send();
                        }
                      }}
                    />
                  </label>
                  <div className="sk-ai-actions">
                    <span className="hint">Ctrl / ⌘ + Enter 发送</span>
                    {active ? (
                      <button
                        type="button"
                        className="small"
                        disabled={busy}
                        onClick={() => void cancel()}
                      >
                        取消本轮
                      </button>
                    ) : (
                      <button
                        type="submit"
                        className="primary small"
                        disabled={busy || !question.trim() || !chatLoaded}
                      >
                        {busy ? '正在提交…' : '发送'}
                      </button>
                    )}
                  </div>
                </Form>
                <p className="hint">对话按本人账号与Skill独立保存；建议不直接写文件。</p>
              </aside>
            )}
          </div>
          <p className="hint mt">预览和AI建议均不代表保存。应用到草稿后，仍需管理员确认保存。</p>
        </>
      )}
    </CaseDialog>
  );
}
