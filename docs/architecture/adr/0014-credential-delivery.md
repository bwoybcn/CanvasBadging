# ADR-0014: Credential delivery and sharing

Date: 2026-11-13 · Status: Accepted

## Decision
MVP delivery channels:
1. Download of the exact signed JSON-LD (`.json`). Baked PNG/SVG is LATER.
2. Student-controlled share URL `/verify/<share_id>` (128-bit random id). The page links to `credential.json` so wallets that support "add from URL" can import it.
3. Copyable details and the LinkedIn Add-to-Profile link (`startTask=CERTIFICATION_NAME`, `name`, `organizationId` XOR `organizationName`, issue/expiry month and year, `certUrl`, `certId` = credential id).
4. Wallet guide documenting tested import paths (Learner Credential Wallet file/URL import) and known limits.

The OB 3.0 API (Host / Service Provider roles, OAuth 2 with dynamic client registration) is not required for issuers and is deferred to §21 2F. VC-API/CHAPI wallet exchange is also deferred. A `CredentialTransport` interface keeps room for them.
