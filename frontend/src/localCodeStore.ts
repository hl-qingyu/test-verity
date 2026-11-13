import type { Change, DirectoryHandle, ReadResult } from './localCodeFiles';
import { compareReads } from './localCodeFiles';
import { snapshotTime } from './snapshotTime';

export type Binding = { key: string; handle: DirectoryHandle; scope: string[]; sequence: number };
export type Snapshot = ReadResult & {
  key: string;
  sequence: number;
  scope: string[];
  foundAt: string;
  startedAt: string;
  name?: string;
  changes: Change[];
};
export type SnapshotSummary = Pick<
  Snapshot,
  'sequence' | 'foundAt' | 'startedAt' | 'changes' | 'name'
>;

export function snapshotName(snapshot: Pick<Snapshot, 'name' | 'foundAt' | 'sequence'>): string {
  return snapshot.name || snapshotTime(snapshot.foundAt) || `读取 #${snapshot.sequence}`;
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('verity-local-code', 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore('bindings', { keyPath: 'key' });
      request.result.createObjectStore('snapshots', { keyPath: ['key', 'sequence'] });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error('local_storage_unavailable'));
    request.onblocked = () => reject(new Error('local_storage_unavailable'));
  });
}

export async function loadBinding(key: string): Promise<Binding | undefined> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('bindings').objectStore('bindings').get(key);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('local_storage_unavailable'));
    });
  } finally {
    db.close();
  }
}

export async function bindDirectory(
  key: string,
  handle: DirectoryHandle,
  scope: string[],
): Promise<void> {
  const previous = await loadBinding(key);
  if (previous && !(await previous.handle.isSameEntry(handle)))
    throw new Error('directory_mismatch');
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('bindings', 'readwrite');
      const store = tx.objectStore('bindings');
      const get = store.get(key);
      get.onsuccess = () => {
        const latest: Binding | undefined = get.result;
        if ((latest?.sequence || 0) !== (previous?.sequence || 0)) {
          tx.abort();
          return;
        }
        store.put({ key, handle, scope: latest?.scope || scope, sequence: latest?.sequence || 0 });
      };
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(new Error('local_storage_unavailable'));
      tx.onerror = () => reject(new Error('local_storage_unavailable'));
    });
  } finally {
    db.close();
  }
}

export async function loadSnapshot(key: string, sequence: number): Promise<Snapshot | undefined> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction('snapshots').objectStore('snapshots').get([key, sequence]);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('local_storage_unavailable'));
    });
  } finally {
    db.close();
  }
}

export async function appendSnapshot(
  binding: Binding,
  result: ReadResult,
  scope: string[],
  startedAt: string,
): Promise<Snapshot> {
  const previous = binding.sequence ? await loadSnapshot(binding.key, binding.sequence) : undefined;
  if (binding.sequence && !previous) throw new Error('local_history_missing');
  const foundAt = new Date().toISOString();
  const snapshot: Snapshot = {
    ...result,
    key: binding.key,
    sequence: binding.sequence + 1,
    scope: [...scope],
    startedAt,
    foundAt,
    name: snapshotTime(foundAt),
    changes: compareReads(previous, result, previous?.scope || [], scope),
  };
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(['bindings', 'snapshots'], 'readwrite');
      const bindings = tx.objectStore('bindings');
      let conflict = false;
      const get = bindings.get(binding.key);
      get.onsuccess = () => {
        if (get.result?.sequence !== binding.sequence) {
          conflict = true;
          tx.abort();
          return;
        }
        tx.objectStore('snapshots').add(snapshot);
        bindings.put({ ...binding, scope: [...scope], sequence: snapshot.sequence });
      };
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(new Error(conflict ? 'local_read_conflict' : 'local_storage_full'));
      tx.onerror = () => reject(new Error('local_storage_full'));
    });
  } finally {
    db.close();
  }
  return snapshot;
}

export async function readHistory(
  key: string,
  before = Number.MAX_SAFE_INTEGER,
): Promise<SnapshotSummary[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const summaries: SnapshotSummary[] = [];
      const request = db
        .transaction('snapshots')
        .objectStore('snapshots')
        .openCursor(IDBKeyRange.bound([key, 1], [key, before], false, true), 'prev');
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor || summaries.length === 20) {
          resolve(summaries);
          return;
        }
        const { sequence, foundAt, startedAt, changes, name } = cursor.value as Snapshot;
        summaries.push({ sequence, foundAt, startedAt, changes, name });
        cursor.continue();
      };
      request.onerror = () => reject(new Error('local_storage_unavailable'));
    });
  } finally {
    db.close();
  }
}
