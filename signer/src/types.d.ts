declare module "@digitalbazaar/ed25519-multikey" {
  export interface Ed25519KeyPair {
    id?: string;
    controller?: string;
    publicKeyMultibase: string;
    secretKeyMultibase?: string;
    export(opts: {
      publicKey?: boolean;
      secretKey?: boolean;
      includeContext?: boolean;
    }): Promise<{ publicKeyMultibase: string; secretKeyMultibase?: string }>;
  }
  export function generate(opts?: { id?: string; controller?: string }): Promise<Ed25519KeyPair>;
  export function from(key: Record<string, unknown>): Promise<Ed25519KeyPair>;
}
