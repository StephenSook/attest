import pytest
from pydantic import ValidationError

from app.models import Answer, VerificationResult, verification_result_schema


def test_schema_is_generated_from_the_model() -> None:
    schema = verification_result_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) >= {
        "reached_office",
        "office_name_confirmed",
        "accepting_new_patients",
        "accepts_plan",
    }


def test_unknown_is_a_first_class_answer() -> None:
    result = VerificationResult(
        reached_office=True,
        office_name_confirmed=Answer.YES,
        accepting_new_patients=Answer.UNKNOWN,
        accepts_plan=Answer.UNKNOWN,
    )
    assert result.accepting_new_patients is Answer.UNKNOWN


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        VerificationResult(
            reached_office=True,
            office_name_confirmed=Answer.YES,
            accepting_new_patients=Answer.YES,
            accepts_plan=Answer.YES,
            invented_field="nope",  # type: ignore[call-arg]
        )
