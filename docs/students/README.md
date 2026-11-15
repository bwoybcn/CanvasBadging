# Keeping and sharing your badges (student guide)

This is the long version of the in-app page **My badges → How to keep your badges**.

## What you get

Each badge you earn comes with a **credential file**: the badge in signed **Open Badges 3.0**
form. The university's issuer signs it with its key, so anyone can check that it is genuine and unchanged, and whether the university
has revoked it, without logging in to Canvas or to this service.

In **My badges** you can, for each badge:

| Action | What it does |
|---|---|
| **Download certificate (PDF)** | Saves a one-page certificate to print or attach to an application. Your name is on it unless you untick **Put my name on the certificate**. If the badge has a public link, the certificate carries a QR code that opens it. |
| **Download badge image** | Saves the picture of the badge (PNG), for a CV, slides or an email signature. |
| **Download credential file** | Saves the signed credential file (`.json`), for wallets and for checking. It is yours to keep. |
| **Turn on public link** | Creates a page anyone with the link can open to check the badge. Off until you turn it on. |
| **Show my name / Show evidence** | Choose what the public page shows. The preview shows exactly what will be visible before you turn the link on. |
| **Stop sharing** | Turns the link off straight away. Your badge is **not** revoked, and credential files you downloaded keep verifying. Turning sharing on again creates a new link. |
| **Add to LinkedIn** | Copyable values for LinkedIn's "Add license or certification" form, and a button that opens that form pre-filled. |

## The certificate and the credential file

The certificate is a copy for people to read. It says so at the bottom, and it shows the date it
was produced. The proof is the credential file, or the public page behind the QR code, because
those show whether the badge is still valid today.

- To get a QR code on the certificate, turn on the public link first, then download the
  certificate. Without a public link the certificate tells the reader to ask you for the
  credential file and where to check it.
- The QR code opens your public link. If you stop sharing, the code on certificates you already
  printed stops working. Turning sharing on again creates a new link, so download a new
  certificate.
- The certificate has your name on it only because you asked for it; the name is not added to the
  credential file. People who scan the code see your name on the public page only if you ticked
  **Show my name** there.
- A revoked or suspended badge has no certificate. An expired badge still has one, and it shows
  the date the badge expired.
- Certificates print Latin, Greek and Cyrillic letters. If your name uses another script, untick
  **Put my name on the certificate** to download it without the name.

## Privacy

- Nothing is public until you turn on a link.
- Link addresses are long random codes. They cannot be guessed from your name, student number or
  other badges.
- Public pages ask search engines not to index them. Anyone you give the link to can still open it
  and pass it on.
- Never shown: your email, Canvas login, marks, grades, submissions, your other badges or your
  course roster. Your name appears only if you tick **Show my name**. Link previews in messaging
  and social apps show the badge and the university, never your name.
- By default your name is not inside the credential file either; the file identifies you by a
  salted fingerprint of your university email address. (An institution can change this policy;
  if it does, the sharing preview tells you.)

## Adding a badge to LinkedIn

1. Turn on the public link (LinkedIn shows it as the **Credential URL**, so people can check it).
2. Select **Open LinkedIn's Add certification form**. LinkedIn opens in a new tab; you sign in to
   LinkedIn yourself.
3. Check each field. LinkedIn may not pre-fill every value; use the **Copy** buttons for anything
   missing: Name, Issuing organization, Issue date, Expiration date, Credential ID, Credential URL.
4. Save on LinkedIn.

LinkedIn does not import Open Badges files. What it stores is the text you save plus the link.

## Digital wallets

See [wallets.md](wallets.md) for tested import routes and known limits.

## Before you leave the university

Your Canvas account closes when you leave. Your badges do not depend on it.

1. Open every badge in **My badges**, download its certificate and its credential file, and keep
   them somewhere personal (cloud storage, a personal email to yourself, a wallet app).
2. Keep any public link you have used on a CV or LinkedIn turned on. Links keep working after
   your Canvas account closes, unless you or the university turn them off.
3. To check a file later, upload it at `https://<verification host>/verify` or use any Open
   Badges 3.0 verifier, for example [VerifierPlus](https://verifierplus.org/).

Checking a file relies on the university keeping its public verification information online (its
issuer keys and revocation list). See
[../administration/preserving-verification.md](../administration/preserving-verification.md).
