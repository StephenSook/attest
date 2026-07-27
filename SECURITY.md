# Security policy

## Reporting

Report vulnerabilities privately to stephensookra@gmail.com. Please do not
open a public issue for a security problem. Expect a reply within 72 hours.

## What this project treats as security-relevant

- **Outward dialing.** The judge sandbox is the only path a non-operator can
  use to make the system place a phone call. It is consent-gated, capped,
  one-call-per-number, US-only, premium-rate blocked, and kill-switchable.
  Any bypass of those rails is a security bug.
- **Secrets.** No secret may reach the browser or the repository. The signing
  key, API credentials, and operator/judge keys live only in the deployment
  environment. `gitleaks` runs over full history in CI.
- **Server-side fetches.** Any URL fetched server-side goes through
  resolve-then-pin validation (`backend/app/security/ssrf.py`) with the
  loopback, private, link-local, and cloud-metadata blocklist.
- **Webhook verification.** Signatures are verified over raw request bytes
  with a constant-time comparison and a replay window.
- **Attestation integrity.** Certificates are signed with Ed25519 over a
  canonical JSON form; the public key is published so anyone can verify.
  A signature that validates for a document it should not is a security bug.

## Out of scope

Rate limits on public read-only endpoints, and the documented residual that a
holder of the secret judge key can cause at most fifteen disclosed, capped,
one-per-number demo calls (see `docs/FACTS.md`).
