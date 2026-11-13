// SPDX-License-Identifier: AGPL-3.0-or-later
/** Encrypted private key storage in schema `keys` (readable only by the signer's DB role). */
import pg from "pg";

import type { Envelope } from "./envelope.js";

export interface StoredKey extends Envelope {
  issuerKeyId: string;
  kekRef: string;
  isDev: boolean;
}

export interface KeyStore {
  insert(key: StoredKey): Promise<"created" | "exists">;
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

  async devKeysPresent(): Promise<boolean> {
    const res = await this.pool.query(
      "SELECT EXISTS (SELECT 1 FROM keys.private_keys WHERE is_dev AND destroyed_at IS NULL) AS present",
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
