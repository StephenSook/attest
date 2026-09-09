# Security policy

## Reporting

Report vulnerabilities privately to stephensookra@gmail.com. Please do not
open a public issue for a security problem. Expect a reply within 72 hours.

## What this project treats as security-relevant

- **Outward dialing.** The public judge sandbox is closed by default. When an
  operator explicitly enables it, it is consent-gated, capped,
  one-call-per-number, US-only, premium-rate blocked, and kill-switchable.
  Any bypass of those rails is a security bug.
- **Secrets.** No secret may reach the browser or the repository. The signing
  key, API credentials, and operator/judge keys live only in the deployment
  environment. `gitleaks` runs over full history in CI.
- **Server-side fetches.** No production path fetches caller-supplied URLs.
  The reserved helper at `backend/app/security/ssrf.py` rejects loopback,
  private, link-local, and cloud-metadata destinations before any future use.
- **Webhook verification.** When a signing secret exists, signatures are
  verified over raw request bytes with a constant-time comparison and replay
  window. Current unsigned CALL-E events are hints only and trigger an
  authenticated API re-fetch before any state change.
- **Attestation integrity.** Certificates are signed with Ed25519 over a
  canonical JSON form; the public key is published so anyone can verify.
  A signature that validates for a document it should not is a security bug.

## Out of scope

Rate limits on public read-only endpoints, and the documented residual that,
if an operator explicitly enables the sandbox, a holder of the secret judge
key can cause at most fifteen disclosed, capped, one-per-number demo calls
(see `docs/FACTS.md`).
