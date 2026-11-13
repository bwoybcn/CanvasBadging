// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Envelope encryption for private keys (ADR-0005): each secret gets its own random 256-bit DEK
 * (AES-256-GCM); the DEK is wrapped by the KEK. Layout of each blob: iv(12) | tag(16) | data.
 */
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

function seal(key: Buffer, plaintext: Buffer, aad: Buffer): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(aad);
  const data = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), data]);
}

function open(key: Buffer, blob: Buffer, aad: Buffer): Buffer {
  const decipher = createDecipheriv("aes-256-gcm", key, blob.subarray(0, 12));
  decipher.setAAD(aad);
  decipher.setAuthTag(blob.subarray(12, 28));
  return Buffer.concat([decipher.update(blob.subarray(28)), decipher.final()]);
}

export interface Envelope {
  ciphertext: Buffer;
  dekWrapped: Buffer;
}

/** `aad` binds the ciphertext to its key id, so rows cannot be swapped between keys. */
export function encrypt(kek: Buffer, secret: string, aad: string): Envelope {
  const dek = randomBytes(32);
  const aadBuf = Buffer.from(aad);
  const envelope = {
    ciphertext: seal(dek, Buffer.from(secret, "utf8"), aadBuf),
    dekWrapped: seal(kek, dek, aadBuf),
  };
  dek.fill(0);
  return envelope;
}

export function decrypt(kek: Buffer, envelope: Envelope, aad: string): string {
  const aadBuf = Buffer.from(aad);
  const dek = open(kek, envelope.dekWrapped, aadBuf);
  try {
    return open(dek, envelope.ciphertext, aadBuf).toString("utf8");
  } finally {
    dek.fill(0);
  }
}
