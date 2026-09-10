"""Distribution checks stay separate from product and uptime checks."""

from pathlib import Path


def test_distribution_monitor_downloads_and_verifies_the_apk() -> None:
    root = Path(__file__).parent.parent
    workflow = (root / ".github" / "workflows" / "distribution.yml").read_text()
    uptime = (root / ".github" / "workflows" / "uptime.yml").read_text()
    checksum = (root / "docs" / "mobile" / "attest-pocket.apk.sha256").read_text()

    assert "actions/checkout@v7" in workflow
    assert "attest-pocket.apk" in workflow
    assert "sha256sum" in workflow
    assert "PK\\x03\\x04" in workflow
    assert "110733361" in workflow
    assert "attest-pocket.apk" not in uptime
    assert "20c67c6524610212c45ef9141c5567d7a692542cd020e1c8084984cecee587eb" in checksum
