// SPDX-License-Identifier: AGPL-3.0-or-later
import type { KeyRecord, KeyStore, StoredKey } from "../src/store.js";

export class MemoryStore implements KeyStore {
  rows = new Map<string, StoredKey & { retiredAt: Date | null; destroyedAt: Date | null }>();
  async insert(key: StoredKey) {
    if (this.rows.has(key.issuerKeyId)) return "exists" as const;
    this.rows.set(key.issuerKeyId, { ...key, retiredAt: null, destroyedAt: null });
    return "created" as const;
  }
  async get(id: string): Promise<KeyRecord | null> {
    return this.rows.get(id) ?? null;
  }
  async retire(id: string) {
    const r = this.rows.get(id);
    if (!r) return false;
    r.retiredAt ??= new Date();
    return true;
  }
  async destroy(id: string) {
    const r = this.rows.get(id);
    if (!r) return false;
    r.ciphertext = Buffer.alloc(0);
    r.dekWrapped = Buffer.alloc(0);
    r.retiredAt ??= new Date();
    r.destroyedAt ??= new Date();
    return true;
  }
  async devKeysPresent() {
    return [...this.rows.values()].some((r) => r.isDev);
  }
  async ping() {}
  async close() {}
}
