"""Tests for the Scene7 IPS API client.

Nothing here touches the network. The SOAP client is faked, because the two bugs
worth guarding against are both about the *shape* of the call rather than about
what the server says back:

    1. The ``authHeader`` element is declared in two namespaces and only the
       VERSIONED one authenticates. The unversioned one goes out on the wire and
       is silently ignored, which the server reports as "no authentication
       credentials found" while the credentials are visibly present.
    2. That header must carry ``appName`` and be attached to every operation via
       ``_soapheaders``.

Both are asserted directly below, since neither is visible in a passing manual run.
"""

import datetime
import json

import pytest

import scene7api as s7


# --------------------------------------------------------------------------
# parse_params
# --------------------------------------------------------------------------

def test_parse_params_flat_pairs():
    assert s7.parse_params(["companyName=ExampleCo", "limit=10"]) == {
        "companyName": "ExampleCo",
        "limit": "10",
    }


def test_parse_params_splits_on_first_equals_only():
    """Handles and base64 values contain '='. Splitting on all of them corrupts them."""
    params = s7.parse_params(["companyHandle=c|12345", "token=YWJjZA=="])
    assert params["token"] == "YWJjZA=="


def test_parse_params_rejects_a_pair_without_equals():
    with pytest.raises(ValueError, match="key=value"):
        s7.parse_params(["companyName"])


def test_parse_params_accepts_an_empty_value():
    assert s7.parse_params(["companyName="]) == {"companyName": ""}


def test_parse_params_handles_none_and_empty():
    assert s7.parse_params(None) == {}
    assert s7.parse_params([]) == {}


def test_params_json_expresses_nested_types():
    params = s7.parse_params([], '{"nameArray": {"items": ["hero", "banner"]}}')
    assert params["nameArray"]["items"] == ["hero", "banner"]


def test_params_json_overrides_flat_pairs():
    params = s7.parse_params(["companyName=Old"], '{"companyName": "New"}')
    assert params["companyName"] == "New"


def test_params_json_accepts_an_already_decoded_dict():
    assert s7.parse_params([], {"a": 1}) == {"a": 1}


def test_params_json_must_decode_to_an_object():
    with pytest.raises(ValueError, match="JSON object"):
        s7.parse_params([], '["not", "an", "object"]')


# --------------------------------------------------------------------------
# resolve_endpoints
# --------------------------------------------------------------------------

CONFIG = {
    "username": "someone@example.com",
    "password": "s3cret",
    "wsdl_url": "https://config.example/IpsApi.wsdl",
    "service_url": "https://config.example/IpsApiService",
}


def test_every_region_is_https_and_complete():
    for name, urls in s7.REGIONS.items():
        assert urls["wsdl_url"].startswith("https://"), name
        assert urls["service_url"].startswith("https://"), name


def test_region_overrides_the_config():
    wsdl, service = s7.resolve_endpoints(CONFIG, region="emea")
    assert "s7sps3apissl" in wsdl and "s7sps3apissl" in service


def test_region_is_case_insensitive():
    assert s7.resolve_endpoints(CONFIG, region="EMEA") == s7.resolve_endpoints(CONFIG, region="emea")


def test_unknown_region_names_the_known_ones():
    with pytest.raises(ValueError) as excinfo:
        s7.resolve_endpoints(CONFIG, region="antarctica")
    message = str(excinfo.value)
    assert "antarctica" in message
    for known in s7.REGIONS:
        assert known in message


def test_config_endpoints_are_used_when_no_region_is_given():
    assert s7.resolve_endpoints(CONFIG) == (CONFIG["wsdl_url"], CONFIG["service_url"])


def test_missing_config_endpoint_suggests_region():
    with pytest.raises(ValueError, match="--region"):
        s7.resolve_endpoints({"username": "u", "password": "p"})


# --------------------------------------------------------------------------
# resolve_password
# --------------------------------------------------------------------------

def test_password_comes_from_the_environment_first(monkeypatch):
    monkeypatch.setenv("SCENE7_PASSWORD", "from-env")
    assert s7.resolve_password({"password": "from-file"}) == "from-env"


def test_password_falls_back_to_the_config(monkeypatch):
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    assert s7.resolve_password({"password": "from-file"}) == "from-file"


def test_an_empty_environment_variable_does_not_shadow_the_config(monkeypatch):
    monkeypatch.setenv("SCENE7_PASSWORD", "")
    assert s7.resolve_password({"password": "from-file"}) == "from-file"


def test_password_may_be_absent_entirely(monkeypatch):
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    assert s7.resolve_password({}) is None


# --------------------------------------------------------------------------
# redact
# --------------------------------------------------------------------------

def test_redact_removes_every_occurrence():
    assert "hunter2" not in s7.redact("a hunter2 b hunter2", "hunter2")


def test_redact_handles_several_secrets():
    out = s7.redact("user=bob pass=hunter2", "bob", "hunter2")
    assert "bob" not in out and "hunter2" not in out


def test_redact_ignores_none_and_empty_secrets():
    assert s7.redact("unchanged", None, "") == "unchanged"


def test_redact_passes_none_through():
    assert s7.redact(None, "hunter2") is None


def test_redact_coerces_non_string_secrets():
    assert "1234" not in s7.redact("code 1234", 1234)


# --------------------------------------------------------------------------
# The auth header: the bug this client exists to fix
# --------------------------------------------------------------------------

class FakeElement:
    """Stands in for the zeep element factory, recording how it was called."""

    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return ("auth-header", kwargs)


class FakeService:
    def __init__(self):
        self.calls = []

    def getCompanyInfo(self, **kwargs):
        self.calls.append(("getCompanyInfo", kwargs))
        return "company-info"


VERSIONED_NS = "http://www.scene7.com/IpsApi/xsd/2014-04-03"
UNVERSIONED_NS = "http://www.scene7.com/IpsApi/xsd"


class FakeTypes:
    def __init__(self, namespaces):
        self.namespaces = namespaces


class FakeWsdl:
    def __init__(self, namespaces):
        self.types = FakeTypes(namespaces)


class FakeClient:
    """Models the real WSDL: authHeader is declared in BOTH namespaces."""

    def __init__(self, namespaces=(UNVERSIONED_NS, VERSIONED_NS)):
        self.element = FakeElement()
        self.requested_qname = None
        self.service = FakeService()
        self.wsdl = FakeWsdl(list(namespaces))

    def get_element(self, qname):
        namespace = qname.split("}")[0].lstrip("{")
        if namespace not in self.wsdl.types.namespaces:
            raise LookupError(qname)
        self.requested_qname = qname
        return self.element


def test_the_versioned_namespace_is_chosen_over_the_unversioned_one():
    """The regression that cost the most time.

    Both namespaces declare an identical-looking element. The unversioned one is
    rendered onto the wire and then ignored by the server, so picking it produces a
    fault claiming no credentials were sent while they are visible in the envelope.
    """
    assert s7.resolve_auth_header_qname(FakeClient()) == "{%s}authHeader" % VERSIONED_NS


def test_namespace_choice_does_not_depend_on_declaration_order():
    reversed_order = FakeClient(namespaces=(VERSIONED_NS, UNVERSIONED_NS))
    assert s7.resolve_auth_header_qname(reversed_order) == "{%s}authHeader" % VERSIONED_NS


def test_a_future_wsdl_version_is_followed_rather_than_hardcoded():
    """A newer dated namespace should win, without editing this client."""
    future = "http://www.scene7.com/IpsApi/xsd/2030-01-01"
    client = FakeClient(namespaces=(UNVERSIONED_NS, future))
    assert s7.resolve_auth_header_qname(client) == "{%s}authHeader" % future


def test_a_wsdl_without_the_element_is_reported_clearly():
    with pytest.raises(ValueError, match="authHeader"):
        s7.resolve_auth_header_qname(FakeClient(namespaces=()))


def test_build_auth_header_asks_for_the_versioned_element(monkeypatch):
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    client = FakeClient()
    s7.build_auth_header(client, CONFIG)
    assert client.requested_qname == "{%s}authHeader" % VERSIONED_NS


def test_build_auth_header_sends_appname(monkeypatch):
    """Mandatory in the versioned element; omitting it fails zeep validation."""
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    client = FakeClient()
    s7.build_auth_header(client, CONFIG)
    assert client.element.kwargs["appName"]


def test_build_auth_header_carries_the_credentials(monkeypatch):
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    client = FakeClient()
    s7.build_auth_header(client, CONFIG)
    assert client.element.kwargs["user"] == CONFIG["username"]
    assert client.element.kwargs["password"] == CONFIG["password"]


def test_build_auth_header_requests_faults_as_http_200(monkeypatch):
    """Faults arriving as HTTP 500 make zeep raise a transport error instead of parsing them."""
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    client = FakeClient()
    s7.build_auth_header(client, CONFIG)
    assert client.element.kwargs["faultHttpStatusCode"] == 200


def test_build_auth_header_prefers_the_environment_password(monkeypatch):
    monkeypatch.setenv("SCENE7_PASSWORD", "from-env")
    client = FakeClient()
    s7.build_auth_header(client, CONFIG)
    assert client.element.kwargs["password"] == "from-env"


@pytest.mark.parametrize("config", [
    {"password": "p"},
    {"username": "u"},
    {"username": "", "password": "p"},
    {},
])
def test_build_auth_header_refuses_incomplete_credentials(monkeypatch, config):
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="username and password"):
        s7.build_auth_header(FakeClient(), config)


# --------------------------------------------------------------------------
# execute_command
# --------------------------------------------------------------------------

def test_execute_command_attaches_the_auth_header():
    """The second half of the auth bug: a correct header that is never sent."""
    client = FakeClient()
    header = ("auth-header", {})
    s7.execute_command(client, {"name": "getCompanyInfo", "params": {"companyName": "ExampleCo"}}, header)
    _, kwargs = client.service.calls[0]
    assert kwargs["_soapheaders"] == [header]


def test_execute_command_passes_the_parameters_through():
    client = FakeClient()
    s7.execute_command(client, {"name": "getCompanyInfo", "params": {"companyName": "ExampleCo"}}, None)
    _, kwargs = client.service.calls[0]
    assert kwargs["companyName"] == "ExampleCo"


def test_execute_command_tolerates_a_missing_params_key():
    client = FakeClient()
    assert s7.execute_command(client, {"name": "getCompanyInfo"}, None) == "company-info"


def test_execute_command_omits_the_header_when_there_is_none():
    """Under --auth-mode basic the credentials are on the session, not in the envelope."""
    client = FakeClient()
    s7.execute_command(client, {"name": "getCompanyInfo"}, None)
    _, kwargs = client.service.calls[0]
    assert "_soapheaders" not in kwargs


def test_execute_command_rejects_an_unknown_operation():
    with pytest.raises(ValueError, match="noSuchOperation"):
        s7.execute_command(FakeClient(), {"name": "noSuchOperation"}, None)


# --------------------------------------------------------------------------
# Configuration loading and response formatting
# --------------------------------------------------------------------------

def test_load_config_reads_json(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"username": "u"}))
    assert s7.load_config(str(path)) == {"username": "u"}


def test_load_config_raises_on_a_missing_file(tmp_path):
    with pytest.raises(OSError):
        s7.load_config(str(tmp_path / "absent.json"))


def test_load_config_raises_on_malformed_json(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        s7.load_config(str(path))


def test_format_response_as_text():
    assert s7.format_response({"a": 1}, as_json=False) == "{'a': 1}"


def test_format_response_as_json_is_parseable():
    assert json.loads(s7.format_response({"a": 1}, as_json=True)) == {"a": 1}


def test_json_default_renders_dates_as_iso8601():
    out = json.loads(s7.format_response({"when": datetime.datetime(2026, 9, 24, 12, 0)}, as_json=True))
    assert out["when"] == "2026-09-24T12:00:00"


def test_json_default_falls_back_to_str_for_unknown_types():
    class Opaque:
        def __str__(self):
            return "opaque"

    out = json.loads(s7.format_response({"thing": Opaque()}, as_json=True))
    assert out["thing"] == "opaque"


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def test_method_and_params_become_a_command():
    command, args = s7.parse_command_line_args(
        ["--method", "getCompanyInfo", "--params", "companyName=ExampleCo"])
    assert command == {"name": "getCompanyInfo", "params": {"companyName": "ExampleCo"}}
    assert args.method == "getCompanyInfo"


def test_no_method_yields_no_command():
    command, _ = s7.parse_command_line_args([])
    assert command == {}


def test_config_paths_have_defaults():
    _, args = s7.parse_command_line_args([])
    assert args.auth_config == s7.DEFAULT_AUTH_CONFIG
    assert args.command_config == s7.DEFAULT_COMMAND_CONFIG


def test_region_is_restricted_to_known_values():
    with pytest.raises(SystemExit):
        s7.parse_command_line_args(["--region", "antarctica"])


def test_params_json_is_merged_at_parse_time():
    command, _ = s7.parse_command_line_args(
        ["--method", "getAssetsByName", "--params", "companyHandle=c|1",
         "--params-json", '{"nameArray": {"items": ["hero"]}}'])
    assert command["params"]["companyHandle"] == "c|1"
    assert command["params"]["nameArray"]["items"] == ["hero"]


# --------------------------------------------------------------------------
# main(), wired end to end with a fake client
# --------------------------------------------------------------------------

@pytest.fixture
def auth_file(tmp_path):
    path = tmp_path / "auth_config.json"
    path.write_text(json.dumps(CONFIG))
    return str(path)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(s7, "create_client", lambda *a, **k: client)
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    return client


def test_main_runs_a_command_and_reports_success(auth_file, fake_client, capsys):
    code = s7.main(["--auth-config", auth_file, "--method", "getCompanyInfo",
                    "--params", "companyName=ExampleCo"])
    assert code == 0
    assert "company-info" in capsys.readouterr().out


def test_main_sends_the_auth_header_on_the_real_path(auth_file, fake_client):
    s7.main(["--auth-config", auth_file, "--method", "getCompanyInfo"])
    _, kwargs = fake_client.service.calls[0]
    assert kwargs["_soapheaders"], "the operation was called without an auth header"


def test_main_reports_failure_with_a_non_zero_exit_code(auth_file, fake_client, capsys):
    code = s7.main(["--auth-config", auth_file, "--method", "noSuchOperation"])
    assert code == 1
    assert "noSuchOperation" in capsys.readouterr().err


def test_a_failure_message_never_leaks_the_password(auth_file, fake_client, capsys):
    """The error text includes the exception, which can quote the arguments."""
    def explode(**kwargs):
        raise RuntimeError("upstream said: password=%s" % CONFIG["password"])

    fake_client.service.getCompanyInfo = explode
    s7.main(["--auth-config", auth_file, "--method", "getCompanyInfo"])
    captured = capsys.readouterr()
    assert CONFIG["password"] not in captured.err
    assert "REDACTED" in captured.err


def test_list_methods_does_not_need_credentials(auth_file, fake_client, monkeypatch, capsys):
    """--list-methods should work before the credentials are right, for diagnosis."""
    monkeypatch.setattr(s7, "list_available_methods", lambda c: print("Available Services:"))
    code = s7.main(["--auth-config", auth_file, "--list-methods"])
    assert code == 0
    assert "Available Services:" in capsys.readouterr().out


def test_commands_fall_back_to_the_command_config(auth_file, fake_client, tmp_path, capsys):
    command_file = tmp_path / "command_config.json"
    command_file.write_text(json.dumps(
        {"commands": [{"name": "getCompanyInfo", "params": {"companyName": "ExampleCo"}}]}))
    code = s7.main(["--auth-config", auth_file, "--command-config", str(command_file)])
    assert code == 0
    assert fake_client.service.calls[0][0] == "getCompanyInfo"


# --------------------------------------------------------------------------
# --auth-mode basic: credentials on the HTTP session instead of in the envelope
# --------------------------------------------------------------------------

def test_auth_mode_defaults_to_the_soap_header():
    _, args = s7.parse_command_line_args([])
    assert args.auth_mode == "soap"


def test_auth_mode_is_restricted_to_known_values():
    with pytest.raises(SystemExit):
        s7.parse_command_line_args(["--auth-mode", "kerberos"])


def test_basic_mode_sends_no_soap_header(auth_file, fake_client):
    s7.main(["--auth-config", auth_file, "--auth-mode", "basic", "--method", "getCompanyInfo"])
    _, kwargs = fake_client.service.calls[0]
    assert "_soapheaders" not in kwargs


@pytest.fixture
def captured_session(monkeypatch):
    """Intercept the zeep client so create_client can be tested without a network."""
    captured = {}

    def fake_transport(session=None):
        captured["session"] = session
        return "transport"

    class FakeZeepClient:
        def __init__(self, **kwargs):
            self.service = type("S", (), {"_binding_options": {}})()

    monkeypatch.setattr(s7, "Transport", fake_transport)
    monkeypatch.setattr(s7, "Client", FakeZeepClient)
    monkeypatch.delenv("SCENE7_PASSWORD", raising=False)
    return captured


def test_create_client_leaves_the_session_unauthenticated_by_default(captured_session):
    s7.create_client(CONFIG, region="emea")
    assert captured_session["session"].auth is None


def test_create_client_sets_basic_auth_when_asked(captured_session):
    s7.create_client(CONFIG, region="emea", basic_auth=True)
    auth = captured_session["session"].auth
    assert (auth.username, auth.password) == (CONFIG["username"], CONFIG["password"])


def test_create_client_uses_the_environment_password_for_basic(captured_session, monkeypatch):
    monkeypatch.setenv("SCENE7_PASSWORD", "from-env")
    s7.create_client(CONFIG, region="emea", basic_auth=True)
    assert captured_session["session"].auth.password == "from-env"


def test_basic_auth_refuses_incomplete_credentials(captured_session):
    with pytest.raises(ValueError, match="username and password"):
        s7.create_client({"wsdl_url": "w", "service_url": "s"}, basic_auth=True)


def test_the_service_address_is_bound_to_the_resolved_endpoint(captured_session):
    client = s7.create_client(CONFIG, region="emea")
    assert "s7sps3apissl" in client.service._binding_options["address"]
