import { useRef } from 'react';
import { Icon } from './Icon';

// Directory access requires a user-gesture permission picker, not a file upload input.
export function DirectoryPicker({
  disabled,
  onClick,
}: {
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" disabled={disabled} onClick={onClick}>
      <Icon name="folder" />
      选择目录
    </button>
  );
}

export function FilePicker({
  accept,
  multiple,
  disabled,
  onChange,
  directory = false,
}: {
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  onChange: (files: File[]) => void;
  directory?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <span className="file-picker">
      <input
        ref={(node) => {
          input.current = node;
          if (directory) node?.setAttribute('webkitdirectory', '');
          else node?.removeAttribute('webkitdirectory');
        }}
        type="file"
        hidden
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files || []);
          event.currentTarget.value = '';
          if (files.length) onChange(files);
        }}
      />
      <button type="button" disabled={disabled} onClick={() => input.current?.click()}>
        <Icon name="upload" />
        {directory ? '选择目录' : '选择文件'}
      </button>
    </span>
  );
}
