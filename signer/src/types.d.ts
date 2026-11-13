// Minimal typings for untyped Digital Bazaar packages (ESM, no bundled .d.ts).
declare module "@digitalbazaar/ed25519-multikey" {
  export interface Ed25519KeyPair {
    id?: string;
    controller?: string;
    publicKeyMultibase: string;
    secretKeyMultibase?: string;
    signer(): { algorithm: string; id: string; sign(o: { data: Uint8Array }): Promise<Uint8Array> };
    export(opts: {
      publicKey?: boolean;
      secretKey?: boolean;
      includeContext?: boolean;
    }): Promise<{ publicKeyMultibase: string; secretKeyMultibase?: string }>;
  }
  export function generate(opts?: { id?: string; controller?: string; seed?: Uint8Array }): Promise<Ed25519KeyPair>;
  export function from(key: Record<string, unknown>): Promise<Ed25519KeyPair>;
}
declare module "@digitalbazaar/credentials-context" {
  export const contexts: Map<string, unknown>;
}
declare module "@digitalbazaar/data-integrity-context" {
  export const contexts: Map<string, unknown>;
}
declare module "@digitalbazaar/multikey-context" {
  export const contexts: Map<string, unknown>;
}
declare module "@digitalbazaar/vc" {
  export class CredentialIssuancePurpose {
    constructor(opts?: Record<string, unknown>);
  }
  export function issue(opts: Record<string, unknown>): Promise<Record<string, unknown>>;
}
declare module "@digitalbazaar/data-integrity" {
  export class DataIntegrityProof {
    constructor(opts: Record<string, unknown>);
    verificationMethod?: string;
  }
}
declare module "@digitalbazaar/eddsa-rdfc-2022-cryptosuite" {
  export const cryptosuite: Record<string, unknown>;
}
declare module "@digitalbazaar/did-method-key" {
  export function driver(): {
    use(o: { multibaseMultikeyHeader: string; fromMultibase: unknown }): void;
    get(o: { did?: string; url?: string }): Promise<Record<string, unknown>>;
  };
}
declare module "jsonld-signatures" {
  const jsigs: {
    verify(doc: unknown, opts: Record<string, unknown>): Promise<{
      verified: boolean;
      error?: { errors?: Error[]; message?: string; name?: string };
      results?: Array<{ verified: boolean; verificationMethod?: { id?: string }; error?: Error }>;
    }>;
  };
  export default jsigs;
}
declare module "base58-universal" {
  export function decode(s: string): Uint8Array;
  export function encode(b: Uint8Array): string;
}
