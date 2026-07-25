"""The verification result contract.

This Pydantic model IS the source of truth: the strict JSON Schema sent to
CALL-E as result_schema is generated from it, so the two can never drift.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Answer(StrEnum):
    """A three-valued elicited answer. UNKNOWN is a first-class outcome."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class VerificationResult(BaseModel):
    """What one disclosed verification call elicits from a provider's office.

    Facts only, as stated by the respondent. Hedge detection, span grounding,
    reconciliation, and calibration all happen on our side after the call.
    """

    model_config = ConfigDict(extra="forbid")

    reached_office: bool = Field(
        description=(
            "True only if a person or office voicemail at the provider's office was reached."
        )
    )
    office_name_confirmed: Answer = Field(
        description="Did the respondent confirm this is the provider or practice we asked about?"
    )
    accepting_new_patients: Answer = Field(
        description="Is the practice currently accepting new patients?"
    )
    accepts_plan: Answer = Field(
        description=(
            "Does the practice currently accept the named insurance plan? "
            "unknown if not asked or unanswered."
        )
    )
    plan_name: str | None = Field(
        default=None,
        description=(
            "The insurance plan name that was asked about, exactly as asked. "
            "null if none was asked."
        ),
    )
    respondent_role: str | None = Field(
        default=None,
        description=(
            "Who answered, in their words: front desk, office manager, voicemail, "
            "answering service."
        ),
    )
    notes: str | None = Field(
        default=None,
        description="Anything the respondent said that qualifies an answer, verbatim if possible.",
    )


def verification_result_schema() -> dict[str, Any]:
    """The strict JSON Schema handed to CALL-E as result_schema."""
    return VerificationResult.model_json_schema()
