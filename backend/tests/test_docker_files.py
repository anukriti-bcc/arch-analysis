"""Static checks of the Docker setup. They cannot run containers (the author had no Docker); they catch wiring mistakes that would only show up
at `docker compose up`: a missing healthcheck, a DATABASE_URL that does not match the database service, a dependency that is not installed."""
import os
import re
import subprocess

import pytest
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(read("docker-compose.yml"))


def test_three_services_with_the_database_first_in_the_startup_chain(compose):
    s = compose["services"]
    assert set(s) == {"db", "backend", "frontend"}
    assert s["backend"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert s["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"
    for name in ("db", "backend"):
        assert s[name]["healthcheck"]["test"], name


def test_database_url_matches_the_database_service(compose):
    db, be = compose["services"]["db"], compose["services"]["backend"]
    url = be["environment"]["DATABASE_URL"]
    m = re.fullmatch(r"postgresql://(\w+):\$\{POSTGRES_PASSWORD:-([^}]+)\}@db:5432/(\w+)", url)
    assert m, url
    user, default_pw, database = m.groups()
    assert db["environment"]["POSTGRES_USER"] == user and db["environment"]["POSTGRES_DB"] == database
    assert default_pw in db["environment"]["POSTGRES_PASSWORD"]  # both sides use the same default password variable
    assert "pg_isready" in " ".join(db["healthcheck"]["test"]) and f"-U {user}" in " ".join(db["healthcheck"]["test"])


def test_data_persists_in_a_named_volume_and_ports_are_the_documented_ones(compose):
    assert "pgdata" in compose["volumes"]
    assert any(v.startswith("pgdata:/var/lib/postgresql/data") for v in compose["services"]["db"]["volumes"])
    assert "8000:8000" in compose["services"]["backend"]["ports"] and "5173:80" in compose["services"]["frontend"]["ports"]
    assert "./datasets:/app/datasets" in compose["services"]["backend"]["volumes"]  # the UI's default repository path resolves here


def test_the_backend_healthcheck_calls_the_real_health_route(compose):
    hc = " ".join(compose["services"]["backend"]["healthcheck"]["test"])
    assert "/health" in hc and "localhost:8000" in hc
    from fastapi.testclient import TestClient

    from main import app
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and "backend" in r.json()["storage"]


def test_the_backend_image_installs_psycopg_and_git():
    reqs = read("backend", "requirements.txt")
    assert re.search(r"^psycopg\[binary\]", reqs, re.M)
    dockerfile = read("backend", "Dockerfile")
    assert "requirements.txt" in dockerfile and "git" in dockerfile and "uvicorn" in dockerfile and "8000" in dockerfile


def test_the_frontend_image_builds_then_serves_static_files():
    d = read("frontend", "Dockerfile")
    assert "npm run build" in d and "nginx" in d and "/app/dist" in d
    assert os.path.exists(os.path.join(ROOT, "frontend", "nginx.conf"))


def test_the_smoke_script_is_valid_bash_and_checks_persistence():
    path = os.path.join(ROOT, "scripts", "docker_smoke.sh")
    assert os.access(path, os.X_OK)
    r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s = read("scripts", "docker_smoke.sh")
    assert "compose restart backend" in s and "postgresql" in s and "/health" in s
