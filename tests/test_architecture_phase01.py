from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase01_architecture_document_exists_and_is_validated():
    document = (ROOT / "docs" / "PHASE_01_SUPREME_ARCHITECTURE.md").read_text()

    assert "# Phase 01 - Supreme Architecture" in document
    assert "| Status | VALIDATED |" in document
    assert "Level 1 - NEXUS" in document
    assert "Level 2 - NEXUS CORE" in document
    assert "Level 3 - NEXUS SYSTEM" in document


def test_versioned_api_composition_is_present():
    main = (ROOT / "app" / "main.py").read_text()

    assert 'include_router(router, prefix="/api/v1")' in main
    assert '@app.get("/health")' in main


def test_tenant_authorization_boundary_is_present():
    security = (ROOT / "app" / "security.py").read_text()

    assert "ROLE_PERMISSIONS" in security
    assert "x_tenant_id" in security
    assert "tenant_id != x_tenant_id" in security


def test_durable_worker_and_database_persistence_are_present():
    assert (ROOT / "app" / "worker.py").is_file()
    assert (ROOT / "app" / "core" / "database.py").is_file()
    assert (ROOT / "app" / "models.py").is_file()


def test_compose_defines_api_worker_and_postgres():
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "  api:" in compose
    assert "  worker:" in compose
    assert "  postgres:" in compose
