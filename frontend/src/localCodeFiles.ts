// Only read operations are exposed. No code execution, writable handles or network access.
export type DirectoryHandle = {
  kind: 'directory';
  name: string;
  values(): AsyncIterable<DirectoryHandle | CodeFileHandle>;
  queryPermission(options: { mode: 'read' }): Promise<PermissionState>;
  requestPermission(options: { mode: 'read' }): Promise<PermissionState>;
  isSameEntry(other: DirectoryHandle): Promise<boolean>;
};
export type CodeFileHandle = { kind: 'file'; name: string; getFile(): Promise<File> };
export type FileEntry = { path: string; handle: CodeFileHandle };
export type DirectoryTree = { files: FileEntry[]; directories: string[]; excluded: number };
export type CodeFile = { content: string; hash: string; size: number; modifiedAt: number };
export type ReadResult = { files: Record<string, CodeFile>; skipped: Record<string, string> };
export type Change = {
  path: string;
  kind: '新增' | '修改' | '删除' | '纳入范围' | '移出范围' | '未能比较';
};

export function directorySupported(): boolean {
  return globalThis.isSecureContext && 'showDirectoryPicker' in globalThis;
}

export function chooseDirectory(): Promise<DirectoryHandle> {
  if (!directorySupported()) throw new Error('directory_unsupported');
  const picker = globalThis as typeof globalThis & {
    showDirectoryPicker(options: { mode: 'read'; id: string }): Promise<DirectoryHandle>;
  };
  return picker.showDirectoryPicker({ mode: 'read', id: 'verity-local-code' });
}

export async function authorizeDirectory(handle: DirectoryHandle): Promise<void> {
  if ((await handle.requestPermission({ mode: 'read' })) !== 'granted') {
    throw new Error('directory_denied');
  }
}

const excludedNames = new Set([
  '.git',
  '.svn',
  '.hg',
  'node_modules',
  '.venv',
  'venv',
  '__pycache__',
  'target',
  'build',
  'dist',
  '.next',
  '.nuxt',
  '.idea',
  '.vscode',
  '.ssh',
  '.aws',
  '.azure',
  'coverage',
  '.codex',
  '.npmrc',
  '.pypirc',
  '.netrc',
  '.git-credentials',
  'credentials',
  'credentials.json',
  'secrets.json',
  'secrets.yaml',
  'secrets.yml',
]);
export function excludedPath(path: string): boolean {
  return path.split('/').some((part) => {
    const name = part.toLowerCase();
    return (
      excludedNames.has(name) ||
      name === '.env' ||
      name.startsWith('.env.') ||
      /^id_(rsa|dsa|ecdsa|ed25519)(\.|$)/.test(name) ||
      /\.(pem|key|p12|pfx|keystore|jks|log|zip|tar|gz|7z|exe|dll|so|png|jpe?g|gif|webp|pdf|mp4|mp3|woff2?|ttf|ico)$/i.test(
        name,
      )
    );
  });
}

function safeSegment(name: string): boolean {
  return (
    !!name &&
    name !== '.' &&
    name !== '..' &&
    !/[\\/:]/.test(name) &&
    !Array.from(name).some((c) => c.charCodeAt(0) < 32)
  );
}

export async function scanDirectory(
  root: DirectoryHandle,
  signal: AbortSignal,
): Promise<DirectoryTree> {
  if ((await root.queryPermission({ mode: 'read' })) !== 'granted')
    throw new Error('directory_denied');
  const result: DirectoryTree = { files: [], directories: [], excluded: 0 };
  async function visit(directory: DirectoryHandle, prefix: string, depth: number): Promise<void> {
    if (depth > 32) throw new Error('directory_too_large');
    // Reading failures abort the scan. An unreadable directory must never look deleted.
    for await (const handle of directory.values()) {
      signal.throwIfAborted();
      if (!safeSegment(handle.name)) throw new Error('directory_invalid_entry');
      const path = prefix + handle.name;
      if (path.length > 512) throw new Error('directory_too_large');
      if (excludedPath(path)) {
        result.excluded++;
        continue;
      }
      if (handle.kind === 'directory') {
        result.directories.push(path + '/');
        await visit(handle, path + '/', depth + 1);
      } else if (handle.kind === 'file') result.files.push({ path, handle });
    }
  }
  await visit(root, '', 0);
  result.files.sort((a, b) => a.path.localeCompare(b.path));
  result.directories.sort();
  return result;
}

export function inScope(path: string, scope: string[]): boolean {
  return scope.some(
    (item) => item === '/' || item === path || (item.endsWith('/') && path.startsWith(item)),
  );
}

export async function readSelection(
  tree: DirectoryTree,
  scope: string[],
  signal: AbortSignal,
): Promise<ReadResult> {
  const chosen = tree.files.filter((entry) => inScope(entry.path, scope));
  const files: Record<string, CodeFile> = Object.create(null);
  const skipped: Record<string, string> = Object.create(null);
  for (const entry of chosen) {
    signal.throwIfAborted();
    const file = await entry.handle.getFile();
    const bytes = await file.arrayBuffer();
    signal.throwIfAborted();
    const check = await entry.handle.getFile();
    if (check.size !== file.size || check.lastModified !== file.lastModified) {
      throw new Error('local_file_changed');
    }
    let content: string;
    try {
      content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch {
      skipped[entry.path] = '不是UTF-8文本';
      continue;
    }
    if (content.includes('\0')) {
      skipped[entry.path] = '二进制内容';
      continue;
    }
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    files[entry.path] = {
      content,
      size: file.size,
      modifiedAt: file.lastModified,
      hash: Array.from(new Uint8Array(digest), (v) => v.toString(16).padStart(2, '0')).join(''),
    };
  }
  return { files, skipped };
}

export function compareReads(
  previous: ReadResult | undefined,
  current: ReadResult,
  oldScope: string[],
  scope: string[],
): Change[] {
  const paths = new Set([
    ...Object.keys(previous?.files || {}),
    ...Object.keys(previous?.skipped || {}),
    ...Object.keys(current.files),
    ...Object.keys(current.skipped),
  ]);
  return Array.from(paths)
    .sort()
    .flatMap((path): Change[] => {
      if (path in current.skipped || (previous && path in previous.skipped))
        return [{ path, kind: '未能比较' }];
      if (!inScope(path, scope)) return [{ path, kind: '移出范围' }];
      if (previous && !inScope(path, oldScope)) return [{ path, kind: '纳入范围' }];
      const before = previous?.files[path],
        after = current.files[path];
      if (!before && after) return [{ path, kind: '新增' }];
      if (before && !after) return [{ path, kind: '删除' }];
      if (before?.hash !== after?.hash) return [{ path, kind: '修改' }];
      return [];
    });
}
