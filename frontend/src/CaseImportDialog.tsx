import { PageJump } from './PageJump';
import { FilePicker } from './FilePicker';
import { Select } from './FormSelect';
import { useEffect, useRef, useState } from 'react';
import { apiRequest } from './api/http';
import { CaseDialog } from './CaseDialog';
import { CASE_COLUMNS, caseError, parseCaseImportInfo, parseCaseImportPreview } from './caseApi';
import type { CaseMetadata, CaseImportInfo, CaseImportPreview } from './caseApi';

export function CaseImportDialog({
  base,
  metadata,
  categoryId,
  onClose,
  onSaved,
  onSessionEnd,
}: {
  base: string;
  metadata: CaseMetadata;
  categoryId: number | null;
  onClose: () => void;
  onSaved: (count: number) => void;
  onSessionEnd: () => void;
}) {
  const [file, setFile] = useState<File | null>(null),
    [info, setInfo] = useState<CaseImportInfo | null>(null),
    [preview, setPreview] = useState<CaseImportPreview | null>(null),
    [category, setCategory] = useState(categoryId),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const [decisions, setDecisions] = useState<Record<string, 'skip' | 'include'>>({}),
    [matchIndex, setMatchIndex] = useState<Record<string, number>>({}),
    [page, setPage] = useState(1);
  const requestId = useRef(crypto.randomUUID()),
    pending = useRef(false),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function run(action: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      if (alive.current) setError(caseError(e, onSessionEnd));
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function check() {
    if (!file) return;
    await run(async () => {
      let uploaded = info;
      if (!uploaded) {
        const q = new URLSearchParams({ filename: file.name, request_id: requestId.current });
        uploaded = parseCaseImportInfo(
          await apiRequest<unknown>(`${base}/imports?${q}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: file,
            timeoutMs: 30 * 60 * 1000,
          }),
        );
        if (alive.current) setInfo(uploaded);
      }
      const next = parseCaseImportPreview(
        await apiRequest<unknown>(`${base}/imports/${uploaded.id}/review`, {
          method: 'POST',
          body: JSON.stringify({
            category_id: category,
            preview_revision: uploaded.preview_revision,
          }),
          timeoutMs: 180000,
        }),
      );
      if (alive.current) {
        setInfo({ ...uploaded, preview_revision: next.preview_revision });
        setPreview(next);
        setDecisions(
          Object.fromEntries(
            next.items.filter((i) => i.matches.length).map((i) => [i.key, 'skip']),
          ),
        );
        setMatchIndex({});
        setPage(1);
      }
    });
  }
  const duplicates = preview?.items.filter((i) => i.matches.length) || [];
  const skippedDuplicates = duplicates.filter((i) => decisions[i.key] === 'skip').length;
  const count = (preview?.total || 0) - skippedDuplicates;
  async function confirm() {
    if (!info || !preview) return;
    await run(async () => {
      const result = await apiRequest<{ count: number }>(`${base}/imports/${info.id}/confirm`, {
        method: 'POST',
        body: JSON.stringify({
          preview_revision: preview.preview_revision,
          revision: preview.revision,
          duplicate_decisions: decisions,
        }),
        timeoutMs: 180000,
      });
      if (!Number.isSafeInteger(result.count)) throw new Error('case_response_invalid');
      if (alive.current) onSaved(result.count);
    });
  }
  return (
    <CaseDialog title="导入用例" busy={busy} onClose={onClose} wide={!!duplicates.length}>
      <p className="hint">
        支持 XLSX / XLS /
        CSV。自动读取各非空工作表的首个非空行为表头；缺列和空值保留为空，保留原文件用例编号，缺少编号时由平台生成。
      </p>
      <label className="form-field">
        用例分类
        <Select
          disabled={busy}
          value={category ?? ''}
          onChange={(e) => {
            setCategory(e ? Number(e) : null);
            setPreview(null);
          }}
        >
          <option value="">未分类</option>
          {metadata.categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </label>
      <label className="doc-upload-zone">
        <strong>{file ? '重新选择文件' : '选择用例文件'}</strong>
        <FilePicker
          accept=".xlsx,.xls,.csv"
          disabled={busy}
          onChange={(e) => {
            const chosen = e[0];
            if (chosen) {
              setFile(chosen);
              setInfo(null);
              setPreview(null);
              setError('');
              requestId.current = crypto.randomUUID();
            }
          }}
        />
        <span>{file?.name || '选择后自动匹配标准列名，不需要设置字段映射'}</span>
      </label>
      <button className="primary" disabled={busy || !file} onClick={() => void check()}>
        {busy ? '正在处理…' : preview ? '重新检查' : '检查并导入'}
      </button>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {preview && (
        <>
          {preview.errors.length ? (
            <section className="case-import-blocked" role="alert">
              <h3>校验未通过，不能导入</h3>
              <p>请修改原文件后重新上传。不会新增任何用例。</p>
              <ul>
                {preview.errors.slice(0, 100).map((i, n) => (
                  <li key={n}>
                    {i.sheet}
                    {i.row ? ` · 第${i.row}行` : ''} ·{' '}
                    {CASE_COLUMNS.find(([key]) => key === i.field)?.[1] || i.field}：{i.message}
                  </li>
                ))}
              </ul>
              {preview.errors.length > 100 && <p>共{preview.errors.length}项错误，显示前100项。</p>}
            </section>
          ) : (
            <>
              <p className="doc-note">
                识别到{preview.total}条用例
                {duplicates.length
                  ? `，其中${duplicates.length}条与系统已有用例内容重复`
                  : '，未发现与系统已有用例重复'}
                。{preview.skipped ? `另有${preview.skipped}行没有用例内容，已忽略。` : ''}
              </p>
              {!!duplicates.length && (
                <section className="case-duplicate-comparisons">
                  <h3>重复用例对比</h3>
                  <p className="hint">逐条选择“跳过”或“仍然新增”，不会覆盖系统已有用例。</p>
                  {duplicates.slice((page - 1) * 5, page * 5).map((item, index) => {
                    const old = item.matches[matchIndex[item.key] || 0];
                    return (
                      <details className="evidence" key={item.key} open={index === 0}>
                        <summary>
                          {item.sheet} · 第{item.row}行 · {item.values.title || '未填写验证子项'}
                          （系统已有{item.match_count}条）
                        </summary>
                        <div className="case-duplicate-toolbar">
                          <label className="form-field">
                            本次处理
                            <Select
                              disabled={busy}
                              value={decisions[item.key]}
                              onChange={(e) =>
                                setDecisions((v) => ({
                                  ...v,
                                  [item.key]: e as 'skip' | 'include',
                                }))
                              }
                            >
                              <option value="skip">跳过此行</option>
                              <option value="include">仍然新增，保留已有用例</option>
                            </Select>
                          </label>
                          <label className="form-field">
                            对比系统用例
                            <Select
                              value={matchIndex[item.key] || 0}
                              onChange={(e) =>
                                setMatchIndex((v) => ({ ...v, [item.key]: Number(e) }))
                              }
                            >
                              {item.matches.map((r, i) => (
                                <option key={r.id} value={i}>
                                  编号 {r.number} · v{r.version} ·{' '}
                                  {metadata.categories.find((c) => c.id === r.category_id)?.name ||
                                    '未分类'}
                                </option>
                              ))}
                            </Select>
                          </label>
                        </div>
                        <div className="case-duplicate-table">
                          <table>
                            <thead>
                              <tr>
                                <th>字段</th>
                                <th>本次文件</th>
                                <th>
                                  系统用例 {old.number} · v{old.version}
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {CASE_COLUMNS.slice(2).map(([key, name]) => (
                                <tr
                                  key={key}
                                  className={item.values[key] !== old[key] ? 'different' : ''}
                                >
                                  <th scope="row">{name}</th>
                                  <td>{item.values[key] || '—'}</td>
                                  <td>{old[key] || '—'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        {item.match_count > item.matches.length && (
                          <p className="hint">当前展示前{item.matches.length}条系统重复记录。</p>
                        )}
                      </details>
                    );
                  })}
                  {duplicates.length > 5 && (
                    <div className="row">
                      <button disabled={page === 1} onClick={() => setPage((n) => n - 1)}>
                        上一页
                      </button>
                      <span>
                        {page}/{Math.ceil(duplicates.length / 5)}
                      </span>
                      <button
                        disabled={page * 5 >= duplicates.length}
                        onClick={() => setPage((n) => n + 1)}
                      >
                        下一页
                      </button>
                      <PageJump
                        page={page}
                        onChange={setPage}
                        pages={Math.ceil(duplicates.length / 5)}
                        disabled={busy}
                      />
                    </div>
                  )}
                </section>
              )}
              <button className="primary" disabled={busy} onClick={() => void confirm()}>
                {duplicates.length
                  ? `确认新增${count}条，跳过${skippedDuplicates}条`
                  : `确认导入${count}条用例`}
              </button>
              {!!preview.warnings.length && (
                <p className="hint">
                  {preview.warnings.length}行未填写测试人员，保留为空，不影响导入。
                </p>
              )}
            </>
          )}
        </>
      )}
    </CaseDialog>
  );
}
