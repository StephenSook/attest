# Who pays for this

Attest speaks to patients. That is a deliberate product decision and it does not change: the
person harmed by a wrong listing is the person the interface is written for.

This document is the separate question, the one every hackathon project gets asked and most
answer with a guess. Who actually buys a machine that calls provider directories and tells the
truth about what it heard?

Every claim here is public record, cited. Nothing in this file comes from a private conversation.

## The short answer

Not insurers. State regulators, and the auditors who work for them.

## Why not insurers, stated as an incentive rather than an accusation

An insurer sells a plan to an employer partly on the size of its network. A directory listing
1,000 providers is a better sales document than one listing 200, whether or not the extra 800
answer the phone. Meanwhile the insurer's costs go up when members actually reach care.

So a directory that overstates availability is, for the party that maintains it, cheap to keep
and expensive to fix. That is not a claim about any particular company's intent. It is the shape
of the incentive, and it explains why the problem has persisted through a decade of documented
studies without the parties who own the data solving it.

An audit tool sold to the party whose numbers it would embarrass has one customer and no way to
make that customer act on the findings. That is the wrong side of the table.

## Why regulators, with the receipts

The New York State Office of the Attorney General published
**"Inaccurate and Inadequate: Health Plans' Mental Health Provider Directories"** in December
2023. Its method is, almost exactly, what Attest automates:

- A statewide **secret shopper survey of 13 health plans**.
- Staff called providers listed in each plan's directory, posing as consumers seeking treatment,
  attempting to book an appointment for an adult or child.
- **Out of nearly 400 calls, only 14 percent produced an appointment for in-network care.** The
  other **86 percent were "ghosts": unreachable, not in network, or not accepting new patients.**

Source: <https://ag.ny.gov/sites/default/files/reports/mental-health-report_0.pdf> and the OAG's
own summary at
<https://ag.ny.gov/resources/individuals/health-care-insurance/mental-health-access-new-york>.

That report is not a white paper that went nowhere. It became enforcement:

- A **2025 settlement** with one of the surveyed plans, the first resolution arising from the
  report, after the OAG found that **100 percent** of the mental health providers it called,
  every one of them listed as accepting new patients, was either unreachable or not accepting.
  The plan must contact each provider to confirm participation and availability, and an
  **OAG-approved compliance administrator conducts periodic directory audits for at least two
  years.**
- A **2026 settlement** with another surveyed plan for **$2.5 million** in penalties and fees
  plus member restitution, after the OAG found that more than **80 percent** of the behavioral
  health providers it listed as accepting new patients were effectively unavailable.

Per the house framing rule, the plans are not named here. The regulator named them; we are citing
the enforcement pattern, not accusing anyone.

## The part that matters most

The OAG's own recommendation, from the report, is the product specification:

> Require health plans to conduct regular audits of their provider networks (including secret
> shopper studies) to verify compliance with directory accuracy, network adequacy, and mental
> health parity requirements, and to report the results to regulators, who would make them
> available on a public website.

And, separately, that state regulators should "actively and frequently monitor health insurance
networks through secret shopper surveys and other techniques."

So the mandate already exists, the enforcement is already happening, and settlements already
require **periodic directory audits monitored by a compliance administrator for years at a
time**. Somebody has to place those calls, on a recurring basis, and produce a record that holds
up when a plan disputes it.

Today that work is people with phones and spreadsheets. That is the budget line Attest is
built for.

## Why the abstention layer is the commercial feature, not the science project

An audit that feeds an enforcement action has to survive being challenged. A tool that guesses
produces findings a plan's counsel can dismantle one call at a time.

Attest's output is built for exactly that setting: every answer carries the verbatim transcript
span and character offsets that support it, every uncertain call is an explicit abstention rather
than a soft guess, and the confidence attached to an answer has a measured coverage guarantee
computed on held-out data. The signed attestation record makes a single call independently
checkable by anyone holding the public key, including the party being audited.

Refusing to guess is not a research flourish here. It is the difference between evidence and an
allegation.

## Adjacent buyers, honestly ranked

1. **State AGs and state insurance regulators.** Demonstrated budget, demonstrated method,
   demonstrated appetite. The strongest fit.
2. **Compliance administrators and independent monitors** appointed under settlements, who are
   contractually obliged to audit directories for years and need an instrument.
3. **Patient advocacy organizations and legal aid**, who document access failures to support
   complaints and need records that stand up.
4. **Researchers** running secret-shopper studies, who currently do this by hand. A cited
   JAMA study from July 2024, quoted in the OAG's own settlement document, found only
   **17.8 percent** of mental health clinicians listed as in-network for Medicaid plans were
   reachable, accepted Medicaid, and could offer a new patient appointment.
5. **Insurers**, last and least, and only under a mandate they did not choose.

## What this document is not

It is not a revenue projection, and there is no pricing model here, because we have not sold
anything and inventing a number would be the same failure this project exists to avoid. It is
the sourced answer to "who has the budget and the reason", and every figure in it can be checked
against the linked public record.
