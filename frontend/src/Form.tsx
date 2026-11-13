import { useState } from 'react';
import type { ComponentProps } from 'react';

export function Form({
  children,
  onSubmit,
  validationMessage,
  ...props
}: ComponentProps<'form'> & { validationMessage?: string }) {
  const [error, setError] = useState('');
  return (
    <form
      {...props}
      noValidate
      onSubmit={(event) => {
        const invalid = Array.from(event.currentTarget.elements).find(
          (control) =>
            (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement) &&
            control.willValidate &&
            !control.validity.valid,
        );
        const missing = event.currentTarget.querySelector<HTMLButtonElement>(
          '[data-select-required][data-select-empty]:not(:disabled)',
        );
        if (invalid || missing) {
          event.preventDefault();
          setError(
            validationMessage ??
              (invalid instanceof HTMLInputElement || invalid instanceof HTMLTextAreaElement
                ? invalid.validity.valueMissing
                  ? '请填写必填项。'
                  : '输入格式或长度不符合要求，请检查当前聚焦的字段。'
                : '请选择必填选项。'),
          );
          (invalid instanceof HTMLElement ? invalid : missing)?.focus();
          return;
        }
        setError('');
        onSubmit?.(event);
      }}
    >
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {children}
    </form>
  );
}
