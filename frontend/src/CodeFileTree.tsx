import { useMemo, useState } from 'react';

export function CodeFileTree({
  paths,
  selected,
  onChange,
  onPreview,
  disabled = false,
}: {
  paths: string[];
  selected: string[];
  onChange: (paths: string[]) => void;
  onPreview?: (path: string) => void;
  disabled?: boolean;
}) {
  const pageSize = 200;
  const [search, setSearch] = useState('');
  const visible = useMemo(
    () => paths.filter((path) => path.toLowerCase().includes(search.toLowerCase())),
    [paths, search],
  );
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const tree = useMemo(() => {
    const root: FileTreeNode = {
      name: '',
      path: '',
      children: new Map(),
      fileCount: 0,
      selectedCount: 0,
    };
    for (const file of visible) {
      const parts = file.split('/');
      const isSelected = selectedSet.has(file);
      let node = root;
      let prefix = '';
      for (const [index, name] of parts.entries()) {
        prefix = prefix ? `${prefix}/${name}` : name;
        let child = node.children.get(name);
        if (!child) {
          child = {
            name,
            path: prefix,
            children: new Map(),
            fileCount: 0,
            selectedCount: 0,
          };
          node.children.set(name, child);
        }
        child.fileCount++;
        if (isSelected) child.selectedCount++;
        if (index === parts.length - 1) child.filePath = file;
        node = child;
      }
    }
    return [...root.children.values()];
  }, [visible, selectedSet]);
  function toggle(group: string[], checked: boolean) {
    const next = new Set(selected);
    for (const path of group) {
      if (checked) next.add(path);
      else next.delete(path);
    }
    onChange([...next]);
  }
  function filePaths(node: FileTreeNode): string[] {
    if (node.filePath) return [node.filePath];
    return [...node.children.values()].flatMap(filePaths);
  }
  function renderNodes(nodes: FileTreeNode[]): React.ReactNode {
    return (
      <CodeTreeNodes
        nodes={nodes}
        selectedSet={selectedSet}
        onToggle={toggle}
        onPreview={onPreview}
        disabled={disabled}
        pageSize={pageSize}
        filePaths={filePaths}
      />
    );
  }
  return (
    <div className="code-file-picker">
      <label className="form-field">
        搜索文件名或路径
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          disabled={disabled}
        />
      </label>
      <div className="code-file-picker-toolbar">
        <span className="hint">
          已选{selected.length} / {paths.length}个文件
        </span>
        <div className="row">
          <button
            type="button"
            className="small"
            disabled={disabled || !visible.length}
            onClick={() => toggle(visible, true)}
          >
            选择当前可见文件
          </button>
          <button
            type="button"
            className="ghost small"
            disabled={disabled || !selected.length}
            onClick={() => onChange([])}
          >
            清空
          </button>
        </div>
      </div>
      <div className="code-file-tree">
        {renderNodes(tree)}
        {!visible.length && <p className="hint">没有匹配文件。</p>}
      </div>
    </div>
  );
}

type FileTreeNode = {
  name: string;
  path: string;
  filePath?: string;
  children: Map<string, FileTreeNode>;
  fileCount: number;
  selectedCount: number;
};

function CodeTreeNodes({
  nodes,
  selectedSet,
  onToggle,
  onPreview,
  disabled,
  pageSize,
  filePaths,
}: {
  nodes: FileTreeNode[];
  selectedSet: Set<string>;
  onToggle: (group: string[], checked: boolean) => void;
  onPreview?: (path: string) => void;
  disabled: boolean;
  pageSize: number;
  filePaths: (node: FileTreeNode) => string[];
}) {
  const [limit, setLimit] = useState(pageSize);
  return (
    <>
      {nodes.slice(0, limit).map((node) =>
        node.filePath ? (
          <label className="check-label code-tree-file" key={node.path}>
            <input
              type="checkbox"
              disabled={disabled}
              checked={selectedSet.has(node.filePath)}
              onChange={(event) => onToggle([node.filePath!], event.target.checked)}
            />
            {onPreview ? (
              <button
                type="button"
                className="link"
                disabled={disabled}
                title={node.path}
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onPreview(node.path);
                }}
              >
                {node.name}
              </button>
            ) : (
              <span title={node.path}>{node.name}</span>
            )}
          </label>
        ) : (
          <CodeTreeDirectory
            key={node.path}
            node={node}
            selectedSet={selectedSet}
            onToggle={onToggle}
            onPreview={onPreview}
            disabled={disabled}
            pageSize={pageSize}
            filePaths={filePaths}
          />
        ),
      )}
      {nodes.length > limit && (
        <button
          type="button"
          className="ghost small"
          disabled={disabled}
          onClick={() => setLimit((current) => current + pageSize)}
        >
          显示更多（剩余 {nodes.length - limit} 项）
        </button>
      )}
    </>
  );
}

function CodeTreeDirectory({
  node,
  selectedSet,
  onToggle,
  onPreview,
  disabled,
  pageSize,
  filePaths,
}: {
  node: FileTreeNode;
  selectedSet: Set<string>;
  onToggle: (group: string[], checked: boolean) => void;
  onPreview?: (path: string) => void;
  disabled: boolean;
  pageSize: number;
  filePaths: (node: FileTreeNode) => string[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="code-tree-directory"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <label className="check-label" onClick={(event) => event.stopPropagation()}>
          <input
            type="checkbox"
            disabled={disabled}
            checked={node.selectedCount === node.fileCount}
            ref={(element) => {
              if (element)
                element.indeterminate =
                  node.selectedCount > 0 && node.selectedCount < node.fileCount;
            }}
            onChange={(event) => onToggle(filePaths(node), event.target.checked)}
          />
          {node.name}/{' '}
          <span className="hint">
            {node.selectedCount}/{node.fileCount}
          </span>
        </label>
      </summary>
      {open && (
        <CodeTreeNodes
          nodes={[...node.children.values()]}
          selectedSet={selectedSet}
          onToggle={onToggle}
          onPreview={onPreview}
          disabled={disabled}
          pageSize={pageSize}
          filePaths={filePaths}
        />
      )}
    </details>
  );
}
