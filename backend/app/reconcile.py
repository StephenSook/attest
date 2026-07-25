"""Fellegi-Sunter reconciliation: bind what the call elicited to what the
directory claims, and show the arithmetic.

Implemented directly (like the conformal core) so every number is inspectable:
each field contributes log2(m/u) evidence when the call AGREES with the
directory record and log2((1-m)/(1-u)) when it disagrees, on top of a prior
taken from the published audit literature. The waterfall figure is exactly
this column of numbers, drawn.

m = P(field agrees | record is accurate), u = P(field agrees | record is
inaccurate). Priors are fixed and documented here, not fitted, and every
value is stated in the figure. UNKNOWN answers contribute nothing: no
evidence is no evidence.
"""

import math
from dataclasses import dataclass

from app.models import Answer

# Federal audit literature: roughly half of directory listings inaccurate.
# Prior odds accurate:inaccurate = 1:1, log odds 0. Stated, not hidden.
PRIOR_LOG_ODDS = 0.0

# (m, u) per field. Conservative, documented, fixed.
_FIELD_PARAMS: dict[str, tuple[float, float]] = {
    # Reaching a working line for the named practice is strong evidence.
    "office_name_confirmed": (0.95, 0.30),
    # An accepting-new-patients answer matching the listing.
    "accepting_new_patients": (0.90, 0.35),
    # The stated plan participation matching the listing.
    "accepts_plan": (0.85, 0.25),
}

VERIFIED_THRESHOLD = 0.85
CONTRADICTED_THRESHOLD = 0.30


@dataclass(frozen=True)
class FieldContribution:
    field: str
    call_answer: str
    directory_claim: str
    agreed: bool | None  # None when the call produced no evidence
    weight_bits: float


@dataclass(frozen=True)
class Reconciliation:
    contributions: tuple[FieldContribution, ...]
    prior_log_odds: float
    posterior_log_odds: float
    posterior_probability: float
    verdict: str  # verified | contradicted | unverifiable


def _weight(field: str, agreed: bool) -> float:
    m, u = _FIELD_PARAMS[field]
    if agreed:
        return math.log2(m / u)
    return math.log2((1 - m) / (1 - u))


def reconcile(
    call_answers: dict[str, Answer],
    directory_claims: dict[str, Answer],
) -> Reconciliation:
    """Compare elicited answers to directory claims, field by field."""
    contributions: list[FieldContribution] = []
    log_odds = PRIOR_LOG_ODDS
    evidence_fields = 0

    for field in _FIELD_PARAMS:
        answer = call_answers.get(field, Answer.UNKNOWN)
        claim = directory_claims.get(field, Answer.UNKNOWN)
        if answer is Answer.UNKNOWN or claim is Answer.UNKNOWN:
            contributions.append(FieldContribution(field, answer.value, claim.value, None, 0.0))
            continue
        agreed = answer is claim
        weight = _weight(field, agreed)
        log_odds += weight
        evidence_fields += 1
        contributions.append(FieldContribution(field, answer.value, claim.value, agreed, weight))

    probability = 1.0 / (1.0 + 2.0 ** (-log_odds))
    if evidence_fields == 0:
        verdict = "unverifiable"
    elif probability >= VERIFIED_THRESHOLD:
        verdict = "verified"
    elif probability <= CONTRADICTED_THRESHOLD:
        verdict = "contradicted"
    else:
        verdict = "unverifiable"

    return Reconciliation(
        contributions=tuple(contributions),
        prior_log_odds=PRIOR_LOG_ODDS,
        posterior_log_odds=log_odds,
        posterior_probability=probability,
        verdict=verdict,
    )
