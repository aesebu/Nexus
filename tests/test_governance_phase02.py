from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase02_governance_document_exists_and_is_validated():
    document = (ROOT / "docs" / "PHASE_02_AUTHORITY_AND_GOVERNANCE.md").read_text()

    assert "# Phase 02 - Authority and Governance" in document
    assert "| Status | VALIDATED |" in document
    assert "Fail-closed command defaults" in document
    assert "Immutable policy versions" in document
    assert "Emergency stop" in document


def test_governance_models_and_routes_are_present():
    models = (ROOT / "app" / "models.py").read_text()
    routes = (ROOT / "app" / "api" / "routes.py").read_text()

    assert "class CommandPolicy(" in models
    assert "class CommandPolicyVersion(" in models
    assert "class AuditEvent(" in models
    assert "class EmergencyStop(" in models
    assert '"/policies/commands"' in routes
    assert '"/commands/{command_id}/approve"' in routes
    assert '"/emergency-stop"' in routes
    assert '"/audit"' in routes


def test_permission_boundary_and_tenant_claim_are_present():
    security = (ROOT / "app" / "security.py").read_text()

    assert "nexus.policy.manage" in security
    assert "nexus.command.approve" in security
    assert "nexus.emergency.stop" in security
    assert "tenant_id != x_tenant_id" in security


def test_governance_scope_is_not_claimed_as_production_risk_engine():
    document = (ROOT / "docs" / "PHASE_02_AUTHORITY_AND_GOVERNANCE.md").read_text()

    assert "Risk scores and machine-learning classifications" in document
    assert "Secret key rotation and external KMS" in document
    assert "external identity provider" in document
