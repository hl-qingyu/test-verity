import { Children, isValidElement, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';

type Choice = { value: string; label: ReactNode; disabled?: boolean };

export function FormSelect({
  label,
  value,
  options,
  onChange,
  disabled = false,
  name,
  required = false,
  className = '',
  hideLabel = false,
  editable = false,
  placeholder,
  maxLength,
  search,
  onSearchChange,
}: {
  label?: string;
  value: string;
  options: Choice[];
  onChange: (value: string) => void;
  disabled?: boolean;
  name?: string;
  required?: boolean;
  className?: string;
  hideLabel?: boolean;
  editable?: boolean;
  placeholder?: string;
  maxLength?: number;
  search?: string;
  onSearchChange?: (value: string) => void;
}) {
  const id = useId(),
    trigger = useRef<HTMLButtonElement | HTMLInputElement>(null),
    list = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  function close(focus = false) {
    if (list.current?.matches(':popover-open')) list.current.hidePopover();
    if (focus) trigger.current?.focus();
  }
  function show() {
    const button = trigger.current,
      panel = list.current;
    if (disabled || !button || !panel) return;
    if (panel.matches(':popover-open')) {
      close();
      return;
    }
    positionPopover(button, panel);
    panel.showPopover();
    (
      panel.querySelector<HTMLButtonElement>('[aria-selected=true]:not(:disabled)') ||
      panel.querySelector<HTMLButtonElement>('button:not(:disabled)')
    )?.focus();
  }
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: Event) => {
      if (
        event.type === 'scroll' &&
        event.target instanceof Node &&
        list.current?.contains(event.target)
      )
        return;
      if (list.current?.matches(':popover-open')) list.current.hidePopover();
    };
    window.addEventListener('resize', dismiss);
    window.addEventListener('scroll', dismiss, true);
    return () => {
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('scroll', dismiss, true);
    };
  }, [open]);
  useEffect(() => {
    if (disabled && list.current?.matches(':popover-open')) list.current.hidePopover();
  }, [disabled]);
  return (
    <span
      className={`${label && !hideLabel ? 'form-field ' : ''}req-select ${className}`}
      onKeyDown={(e) => {
        if (disabled) return;
        const expanded = list.current?.matches(':popover-open');
        if (e.key === 'Escape' && expanded) {
          e.preventDefault();
          e.stopPropagation();
          close(true);
          return;
        }
        if (e.key === 'Tab' && expanded) {
          close(true);
          return;
        }
        if (
          !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key) ||
          (editable && !expanded && ['Home', 'End'].includes(e.key))
        )
          return;
        e.preventDefault();
        if (!expanded) {
          show();
          return;
        }
        const buttons = Array.from(
          list.current?.querySelectorAll<HTMLButtonElement>('[role=option]:not(:disabled)') || [],
        );
        const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next =
          e.key === 'Home'
            ? 0
            : e.key === 'End'
              ? buttons.length - 1
              : (i + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next]?.focus();
      }}
    >
      {label && (
        <span id={`${id}-label`} className={hideLabel ? 'screen-reader' : undefined}>
          {label}
        </span>
      )}
      {name && !editable && <input type="hidden" name={name} value={value} disabled={disabled} />}
      {editable ? (
        <span className="select-editable">
          <input
            ref={(node) => {
              trigger.current = node;
            }}
            role="combobox"
            aria-label={label}
            aria-controls={id}
            aria-expanded={open}
            aria-autocomplete="list"
            value={value}
            name={name}
            disabled={disabled}
            required={required}
            placeholder={placeholder}
            maxLength={maxLength}
            onChange={(e) => onChange(e.target.value)}
          />
          <button
            className="select-suggestion-trigger"
            type="button"
            aria-label="选择常用建议"
            disabled={disabled}
            onClick={show}
          />
        </span>
      ) : (
        <button
          ref={(node) => {
            trigger.current = node;
          }}
          type="button"
          role="combobox"
          className="req-select-trigger"
          aria-labelledby={label ? `${id}-label ${id}-value` : undefined}
          aria-controls={id}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-required={required}
          data-select-required={required || undefined}
          data-select-empty={!value || undefined}
          disabled={disabled}
          onClick={show}
        >
          <span id={`${id}-value`}>
            {options.find((o) => o.value === value)?.label ?? '请选择'}
          </span>
        </button>
      )}
      <span
        ref={list}
        id={id}
        popover="auto"
        role="listbox"
        className="req-select-options"
        aria-label={label || '可选项'}
        onToggle={(e) => setOpen(e.currentTarget.matches(':popover-open'))}
      >
        {onSearchChange && (
          <input
            aria-label="搜索负责人账号"
            placeholder="搜索账号或姓名"
            value={search || ''}
            onChange={(event) => onSearchChange(event.target.value)}
            onKeyDown={(event) => {
              if (!['Escape', 'Tab'].includes(event.key)) event.stopPropagation();
            }}
          />
        )}
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="option"
            tabIndex={-1}
            disabled={o.disabled || disabled}
            aria-selected={value === o.value}
            onClick={() => {
              if (disabled || o.disabled) return;
              close(true);
              onChange(o.value);
            }}
          >
            <span>{o.label}</span>
          </button>
        ))}
        {!options.length && <span className="hint">暂无可选项</span>}
      </span>
    </span>
  );
}

export function selectOptions(children: ReactNode): Choice[] {
  return Children.toArray(children).flatMap((child) => {
    if (
      !isValidElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>(child)
    )
      return [];
    if (child.type !== 'option') return selectOptions(child.props.children);
    return [
      {
        value: String(child.props.value ?? child.props.children ?? ''),
        label: child.props.children,
        disabled: child.props.disabled,
      },
    ];
  });
}

// Option children are configuration only; no native select or option is mounted.
export function Select({
  value,
  defaultValue,
  onChange,
  children,
  'aria-label': label,
  ...rest
}: {
  value?: string | number;
  defaultValue?: string | number;
  onChange?: (value: string) => void;
  children: ReactNode;
  'aria-label'?: string;
  name?: string;
  disabled?: boolean;
  required?: boolean;
  className?: string;
  search?: string;
  onSearchChange?: (value: string) => void;
}) {
  const options = selectOptions(children);
  const [local, setLocal] = useState(String(defaultValue ?? options[0]?.value ?? ''));
  return (
    <FormSelect
      {...rest}
      hideLabel
      label={label}
      value={value === undefined ? local : String(value)}
      options={options}
      onChange={(next) => {
        setLocal(next);
        onChange?.(next);
      }}
    />
  );
}

function positionPopover(button: HTMLElement, panel: HTMLElement) {
  const r = button.getBoundingClientRect(),
    up = window.innerHeight - r.bottom < 180 && r.top > 180;
  Object.assign(panel.style, {
    width: `${Math.min(Math.max(r.width, 180), window.innerWidth - 24)}px`,
    left: `${Math.max(12, Math.min(r.left, window.innerWidth - Math.max(r.width, 180) - 12))}px`,
    top: up ? 'auto' : `${r.bottom + 6}px`,
    bottom: up ? `${window.innerHeight - r.top + 6}px` : 'auto',
    maxHeight: `${Math.max(60, Math.min(280, up ? r.top - 20 : window.innerHeight - r.bottom - 20))}px`,
  });
}

export function ActionMenu({
  label,
  disabled,
  items,
}: {
  label: string;
  disabled: boolean;
  items: { label: string; run: () => void }[];
}) {
  const id = useId(),
    trigger = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLDivElement>(null),
    [open, setOpen] = useState(false);
  function show() {
    if (!trigger.current || !panel.current) return;
    if (panel.current.matches(':popover-open')) {
      panel.current.hidePopover();
      return;
    }
    positionPopover(trigger.current, panel.current);
    panel.current.showPopover();
    panel.current.querySelector<HTMLButtonElement>('button')?.focus();
  }
  return (
    <div
      className="req-actions"
      onKeyDown={(e) => {
        if (e.key === 'Escape' && panel.current?.matches(':popover-open')) {
          e.preventDefault();
          e.stopPropagation();
          panel.current?.hidePopover();
          trigger.current?.focus();
        }
        if (e.key === 'Tab' && panel.current?.matches(':popover-open')) {
          panel.current?.hidePopover();
          trigger.current?.focus();
        }
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
          e.preventDefault();
          if (!panel.current?.matches(':popover-open')) {
            show();
            return;
          }
          const buttons = Array.from(
              panel.current?.querySelectorAll<HTMLButtonElement>('button') || [],
            ),
            i = buttons.indexOf(document.activeElement as HTMLButtonElement);
          buttons[
            e.key === 'Home'
              ? 0
              : e.key === 'End'
                ? buttons.length - 1
                : (i + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
          ]?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        className="ghost small"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={id}
        disabled={disabled}
        onClick={show}
      >
        ⋯
      </button>
      <div
        ref={panel}
        id={id}
        popover="auto"
        role="menu"
        aria-label={label}
        className="req-select-options"
        onToggle={(e) => setOpen(e.currentTarget.matches(':popover-open'))}
      >
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={() => {
              panel.current?.hidePopover();
              trigger.current?.focus();
              item.run();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
