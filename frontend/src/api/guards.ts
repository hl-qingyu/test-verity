export function isRecord(value: unknown, allowArray = false): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && (allowArray || !Array.isArray(value));
}

export function createGuards(errorCode: string) {
  function invalid(): never {
    throw Error(errorCode);
  }
  function obj(value: unknown): Record<string, unknown> {
    return isRecord(value) ? value : invalid();
  }
  function str(value: unknown): string {
    return typeof value === 'string' ? value : invalid();
  }
  function int(value: unknown, min = 1): number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= min
      ? value
      : invalid();
  }
  function bool(value: unknown): boolean {
    return typeof value === 'boolean' ? value : invalid();
  }
  function list<T>(value: unknown, parse: (item: unknown) => T, max = Infinity): T[] {
    return Array.isArray(value) && value.length <= max ? value.map(parse) : invalid();
  }
  function array(value: unknown, max = Infinity): unknown[] {
    return Array.isArray(value) && value.length <= max ? value : invalid();
  }
  function nullable<T>(value: unknown, parse: (item: unknown) => T): T | null {
    return value === null || value === undefined ? null : parse(value);
  }
  function choice<T extends string>(value: unknown, options: Record<T, unknown>): T {
    return typeof value === 'string' && Object.hasOwn(options, value) ? (value as T) : invalid();
  }
  function hash64(value: unknown): string {
    return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value) ? value : invalid();
  }
  return { invalid, obj, str, int, bool, list, array, nullable, choice, hash64 };
}
