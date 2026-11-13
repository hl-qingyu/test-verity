import { apiRequest } from './api/http';

export type DirectoryFile = { path: string; size: number; sha256: string; extension: string };
export type UploadEntry = { path: string; file: File };
const extensions = new Set([
  'html',
  'htm',
  'css',
  'js',
  'ts',
  'jsx',
  'tsx',
  'vue',
  'json',
  'md',
  'txt',
  'svg',
  'png',
  'jpg',
  'jpeg',
  'webp',
]);
const excluded = new Set([
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
export function directoryPathAllowed(path: string) {
  return (
    path.length > 0 &&
    path.length <= 512 &&
    !/[\\:]/.test(path) &&
    !Array.from(path).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127) &&
    path
      .split('/')
      .every(
        (p) =>
          p &&
          !['.', '..'].includes(p) &&
          !excluded.has(p.toLowerCase()) &&
          !p.toLowerCase().startsWith('.env') &&
          !/^id_(rsa|dsa|ecdsa|ed25519)(\.|$)/i.test(p),
      ) &&
    extensions.has(path.split('.').pop()?.toLowerCase() || '')
  );
}
function uniquePaths(paths: string[]) {
  const sorted = [...paths].sort();
  return (
    new Set(paths).size === paths.length &&
    !sorted.some((p, i) => i > 0 && p.startsWith(sorted[i - 1] + '/'))
  );
}
export function selectedDirectory(files: File[]) {
  const name = files[0]?.webkitRelativePath.split('/')[0] || '';
  if (!name || files.some((f) => !f.webkitRelativePath.startsWith(name + '/')))
    throw Error('prototype_directory_unsupported');
  const entries: UploadEntry[] = [],
    skipped: string[] = [];
  for (const file of files) {
    const path = file.webkitRelativePath.slice(name.length + 1);
    if (directoryPathAllowed(path)) entries.push({ path, file });
    else skipped.push(path);
  }
  if (!uniquePaths(entries.map((e) => e.path))) throw Error('prototype_directory_invalid');
  entries.sort((a, b) => a.path.localeCompare(b.path));
  return { name, entries, skipped };
}

function tarHeader(name: string, size: number) {
  const bytes = new Uint8Array(512),
    encoder = new TextEncoder();
  const put = (offset: number, value: string) => bytes.set(encoder.encode(value), offset);
  put(0, name);
  put(100, '0000644\0');
  put(108, '0000000\0');
  put(116, '0000000\0');
  if (size < 8 ** 11) put(124, size.toString(8).padStart(11, '0') + '\0');
  else {
    let remaining = BigInt(size);
    for (let i = 135; i >= 124; i--) {
      bytes[i] = Number(remaining & 255n);
      remaining >>= 8n;
    }
    bytes[124] |= 128;
  }
  put(136, '00000000000\0');
  put(148, '        ');
  put(156, '0');
  put(257, 'ustar\0');
  put(263, '00');
  put(
    148,
    bytes
      .reduce((a, b) => a + b, 0)
      .toString(8)
      .padStart(6, '0') + '\0 ',
  );
  return bytes;
}

// TAR carries browser File blobs without loading their bodies into JavaScript memory.
export function directoryArchive(
  entries: UploadEntry[],
  metadata: {
    name: string;
    description: string;
    group_id: number | null;
    source_id: number | null;
    directory_name: string;
  },
) {
  if (
    !entries.length ||
    entries.some((e) => !directoryPathAllowed(e.path)) ||
    !uniquePaths(entries.map((e) => e.path))
  )
    throw Error('prototype_directory_invalid');
  const manifest = new Blob(
    [
      JSON.stringify({
        metadata,
        files: entries.map((e) => ({ path: e.path, size: e.file.size })),
      }),
    ],
    { type: 'application/json' },
  );
  const parts: BlobPart[] = [];
  function append(name: string, blob: Blob) {
    parts.push(tarHeader(name, blob.size), blob, new Uint8Array((512 - (blob.size % 512)) % 512));
  }
  append('manifest.json', manifest);
  entries.forEach((e, i) => append('f' + i, e.file));
  parts.push(new Uint8Array(1024));
  return new Blob(parts, { type: 'application/x-tar' });
}

export function directoryBase(projectId: number, documentId: number, versionId: number) {
  return `/api/projects/${projectId}/prototypes/directories/${documentId}/versions/${versionId}`;
}
export async function directoryCatalog(
  projectId: number,
  documentId: number,
  versionId: number,
  signal: AbortSignal,
) {
  const value = await apiRequest<unknown>(
    directoryBase(projectId, documentId, versionId) + '/files',
    { signal },
  );
  if (!value || typeof value !== 'object') throw Error('prototype_response_invalid');
  const result = value as Record<string, unknown>;
  if (
    result.document_id !== documentId ||
    result.version_id !== versionId ||
    typeof result.sha256 !== 'string' ||
    !/^[a-f0-9]{64}$/.test(result.sha256) ||
    !Array.isArray(result.files)
  )
    throw Error('prototype_response_invalid');
  const files = result.files.map((entry: unknown): DirectoryFile => {
    if (!entry || typeof entry !== 'object') throw Error('prototype_response_invalid');
    const f = entry as Record<string, unknown>;
    if (
      typeof f.path !== 'string' ||
      !directoryPathAllowed(f.path) ||
      typeof f.size !== 'number' ||
      !Number.isSafeInteger(f.size) ||
      f.size < 0 ||
      typeof f.sha256 !== 'string' ||
      !/^[a-f0-9]{64}$/.test(f.sha256) ||
      f.extension !== f.path.split('.').pop()?.toLowerCase()
    )
      throw Error('prototype_response_invalid');
    return { path: f.path, size: f.size, sha256: f.sha256, extension: String(f.extension) };
  });
  if (!files.length || !uniquePaths(files.map((f) => f.path)))
    throw Error('prototype_response_invalid');
  return files;
}
