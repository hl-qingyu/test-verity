import { useId, useState } from 'react';

export function PageJump(props: {
  page: number;
  pages?: number;
  disabled?: boolean;
  onChange: (page: number) => void;
}) {
  return <PageJumpInput {...props} />;
}

function PageJumpInput({
  page,
  pages,
  disabled = false,
  onChange,
}: {
  page: number;
  pages?: number;
  disabled?: boolean;
  onChange: (page: number) => void;
}) {
  const [draft, setDraft] = useState({ page, pages, value: String(page), error: '' }),
    id = useId();
  if (draft.page !== page || draft.pages !== pages) {
    setDraft({ page, pages, value: String(page), error: '' });
  }
  const { value, error } =
    draft.page === page && draft.pages === pages ? draft : { value: String(page), error: '' };
  const locked = disabled || (pages !== undefined && pages <= 1);
  function jump() {
    if (locked) return;
    const target = Number(value);
    if (
      !/^\d+$/.test(value.trim()) ||
      !Number.isSafeInteger(target) ||
      target < 1 ||
      (pages !== undefined && target > pages)
    ) {
      setDraft({
        page,
        pages,
        value,
        error:
          pages !== undefined ? `请输入1至${pages}之间的整数页码。` : '请输入有效的正整数页码。',
      });
      return;
    }
    setDraft({ page, pages, value, error: '' });
    if (target !== page) onChange(target);
  }
  return (
    <div className="page-jump">
      <div className="row page-jump-controls">
        <label htmlFor={id}>跳至</label>
        <input
          id={id}
          type="text"
          inputMode="numeric"
          aria-label="跳转页码"
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-error` : undefined}
          disabled={locked}
          value={value}
          onChange={(event) => {
            setDraft({ page, pages, value: event.target.value, error: '' });
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              event.stopPropagation();
              jump();
            }
          }}
        />
        <span>页</span>
        <button type="button" className="small" disabled={locked} onClick={jump}>
          确定
        </button>
      </div>
      {error && (
        <span id={`${id}-error`} className="form-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
