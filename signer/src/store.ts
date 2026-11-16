// SPDX-License-Identifier: AGPL-3.0-or-later
/** Encrypted private key storage in schema `keys` (readable only by the signer's DB role). */
import pg from "pg";

import type { Envelope } from "./envelope.js";

export interface StoredKey extends Envelope {
  issuerKeyId: string;
  kekRef: string;
  isDev: boolean;
}

export interface KeyRecord extends Envelope {
  issuerKeyId: string;
  /** Which key-wrapping key protects it: `dev:committed` or `env:SIGNER_KEK`. */
  kekRef: string;
  isDev: boolean;
  retiredAt: Date | null;
  destroyedAt: Date | null;
}

export interface KeyStore {
  insert(key: StoredKey): Promise<"created" | "exists">;
  get(issuerKeyId: string): Promise<KeyRecord | null>;
  /** Stop signing with a key (routine rotation). Its public half stays published by the api. */
  retire(issuerKeyId: string): Promise<boolean>;
  /** Irreversibly erase private material (compromise, or 30 days after retirement). */
  destroy(issuerKeyId: string): Promise<boolean>;
  /**
   * Whether any key that still has private material is a development key: marked `is_dev`, or
   * wrapped with the committed development KEK whatever it was marked as.
   */
  devKeysPresent(): Promise<boolean>;
  ping(): Promise<void>;
  close(): Promise<void>;
}

export class PgKeyStore implements KeyStore {
  private pool: pg.Pool;

  constructor(connectionString: string) {
    this.pool = new pg.Pool({ connectionString, max: 4 });
    // An idle client can be dropped by the server (restart, failover); log it, don't crash.
    this.pool.on("error", (err) => console.error("signer db pool error:", err.message));
  }

  async insert(key: StoredKey): Promise<"created" | "exists"> {
    const res = await this.pool.query(
      `INSERT INTO keys.private_keys (issuer_key_id, ciphertext, dek_wrapped, kek_ref, is_dev)
       VALUES ($1, $2, $3, $4, $5) ON CONFLICT (issuer_key_id) DO NOTHING`,
      [key.issuerKeyId, key.ciphertext, key.dekWrapped, key.kekRef, key.isDev],
    );
    return res.rowCount === 1 ? "created" : "exists";
  }

  async get(issuerKeyId: string): Promise<KeyRecord | null> {
    const res = await this.pool.query(
      `SELECT issuer_key_id, ciphertext, dek_wrapped, kek_ref, is_dev, retired_at, destroyed_at
         FROM keys.private_keys WHERE issuer_key_id = $1`,
      [issuerKeyId],
    );
    const row = res.rows[0];
    if (!row) return null;
    return {
      issuerKeyId: row.issuer_key_id,
      ciphertext: row.ciphertext,
      dekWrapped: row.dek_wrapped,
      kekRef: row.kek_ref,
      isDev: row.is_dev,
      retiredAt: row.retired_at,
      destroyedAt: row.destroyed_at,
    };
  }

  async retire(issuerKeyId: string): Promise<boolean> {
    const res = await this.pool.query(
      `UPDATE keys.private_keys SET retired_at = coalesce(retired_at, now()) WHERE issuer_key_id = $1`,
      [issuerKeyId],
    );
    return res.rowCount === 1;
  }

  async destroy(issuerKeyId: string): Promise<boolean> {
    const res = await this.pool.query(
      `UPDATE keys.private_keys
          SET ciphertext = '\\x'::bytea, dek_wrapped = '\\x'::bytea,
              retired_at = coalesce(retired_at, now()), destroyed_at = coalesce(destroyed_at, now())
        WHERE issuer_key_id = $1`,
      [issuerKeyId],
    );
    return res.rowCount === 1;
  }

  async devKeysPresent(): Promise<boolean> {
    const res = await this.pool.query(
      `SELECT EXISTS (
         SELECT 1 FROM keys.private_keys
          WHERE (is_dev OR kek_ref LIKE 'dev:%') AND destroyed_at IS NULL) AS present`,
    );
    return Boolean(res.rows[0]?.present);
  }

  async ping(): Promise<void> {
    await this.pool.query("SELECT 1");
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}
