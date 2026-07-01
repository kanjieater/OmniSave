"""
API contract tests via schemathesis.

Validates every endpoint defined in the server's OpenAPI spec:
- Response bodies conform to declared JSON schemas (required fields present)
- Content-Type headers match declared media types

Disabled checks:
- not_a_server_error / unsupported_method: SPA catch-all returns 503 for
  wrong-method calls to API endpoints; tracked separately.
- status_code_conformance: unauthenticated requests return 401 which is not
  declared per-endpoint; authenticated-path testing is in the specific suites.
- positive_data_acceptance: some endpoints require non-spec headers (e.g.
  X-Device-ID) that schemathesis doesn't know to provide.

The `client` fixture ensures app modules are initialized (DB connection, staging/
archive dirs) before each generated test case executes.
"""

import json
import os

from hypothesis import HealthCheck, settings
from schemathesis.config import ProjectConfig, ProjectsConfig, SchemathesisConfig
from schemathesis.config._checks import ChecksConfig
from schemathesis.openapi import from_asgi
from main import app

_cfg = SchemathesisConfig(
    projects=ProjectsConfig(
        default=ProjectConfig(
            checks=ChecksConfig.from_dict({
                "not_a_server_error":       {"enabled": False},
                "status_code_conformance":  {"enabled": False},
                "unsupported_method":       {"enabled": False},
                "positive_data_acceptance": {"enabled": False},
            })
        )
    )
)

schema = from_asgi("/openapi.json", app, config=_cfg)


@schema.parametrize()
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_api_contract(case, client):  # client fixture initializes DB + staging dirs
    case.call_and_validate()


def test_uuid_path_params_have_format(client):
    """Catch regression where a UUID path param loses format:uuid and reintroduces schemathesis flakes."""
    spec = client.get("/openapi.json").json()
    UUID_PARAM_NAMES = {"transaction_id", "session_id"}
    violations = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            for param in op.get("parameters", []):
                if param.get("in") == "path" and param["name"] in UUID_PARAM_NAMES:
                    if param.get("schema", {}).get("format") != "uuid":
                        violations.append(f"{method.upper()} {path} → {param['name']}")
    assert not violations, "UUID path params missing format:uuid:\n" + "\n".join(violations)


def test_openapi_spec_is_current(client):
    """Committed openapi.json must match the runtime spec.

    If this fails, regenerate: ./scripts/gen_openapi.sh
    """
    spec_path = os.path.join(os.path.dirname(__file__), "..", "src", "openapi.json")
    with open(spec_path) as f:
        committed = json.load(f)
    runtime = client.get("/openapi.json").json()
    # version is env-var driven (OMNISAVE_VERSION); normalize before compare
    for d in (committed, runtime):
        d.get("info", {}).pop("version", None)
    assert committed == runtime, "server/src/openapi.json is stale — run ./scripts/gen_openapi.sh"
