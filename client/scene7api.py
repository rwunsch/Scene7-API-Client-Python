"""Scene7 / Dynamic Media IPS API client.

A thin generic dispatcher over the IPS API WSDL: every operation the WSDL exposes
is callable without per-operation code.

Authentication
--------------
The WSDL declares a SOAP header::

    <soap:header message="tns:authHeader" part="authHeader" use="literal"/>

``authHeader`` is declared in **two** namespaces, and only one of them works. The
server accepts the header in the **versioned** namespace that the operations
themselves use (for the 2014-04-03 WSDL, ``.../IpsApi/xsd/2014-04-03``). The same
header in the unversioned ``.../IpsApi/xsd`` is accepted by the schema, rendered
onto the wire, and then **ignored**, which the server reports as::

    authenticationFault 10000
    No authentication credentials found in SOAP header or HTTP Basic header

That fault says "no credentials" while the credentials are plainly in the envelope,
so it reads like a transport problem and is not one. The versioned element also
requires ``appName``; omitting it fails client-side validation in zeep.

Measured against the EMEA endpoint on 2026-09-24:

===================================  =======================================
Header form                          Result
===================================  =======================================
unversioned namespace, no appName    fault 10000, no credentials found
unversioned namespace, with appName  fault 10000, no credentials found
versioned namespace, no appName      zeep ValidationError, appName required
versioned namespace, with appName    success
HTTP Basic, no SOAP header           success
===================================  =======================================

So there are two working modes. The SOAP header is the default because it is what
the WSDL declares and it carries ``locale`` and ``gzipResponse`` alongside the
credentials. ``--auth-mode basic`` is kept because it is the shorter path when the
header is being awkward, and because the server's own fault message offers it.

Examples
--------
    # simple, flat parameters
    python3 scene7api.py --method getCompanyInfo --params companyName=ExampleCo

    # complex parameters (arrays and nested types) need JSON
    python3 scene7api.py --method getAssetsByName \\
        --params-json '{"companyHandle":"c|12345","nameArray":{"items":["hero","banner"]}}'

    # pick a region rather than editing the config
    python3 scene7api.py --region emea --method getCompanyInfo --params companyName=ExampleCo
"""

import argparse
import json
import logging
import os
import re
import sys

import requests
from lxml import etree
from requests.auth import HTTPBasicAuth
from zeep import Client, Settings
from zeep.helpers import serialize_object
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport

# The WSDL declares authHeader in both an unversioned and a versioned namespace.
# Only the versioned one authenticates (see the module docstring), so resolve it
# from the schema rather than hardcoding a version that a newer WSDL would break.
AUTH_HEADER_NAME = "authHeader"

# Sent in the header so Scene7's logs attribute the calls to something identifiable.
APP_NAME = "scene7api.py"
APP_VERSION = "2.0"

# Regional endpoints, as published by AEM at /libs/settings/dam/scene7/endpoints.
REGIONS = {
    "na": {
        "wsdl_url": "https://s7sps1apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl",
        "service_url": "https://s7sps1apissl.scene7.com/scene7/services/IpsApiService",
    },
    "emea": {
        "wsdl_url": "https://s7sps3apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl",
        "service_url": "https://s7sps3apissl.scene7.com/scene7/services/IpsApiService",
    },
    "apac": {
        "wsdl_url": "https://s7sps5apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl",
        "service_url": "https://s7sps5apissl.scene7.com/scene7/services/IpsApiService",
    },
}

DEFAULT_AUTH_CONFIG = "auth_config.json"
DEFAULT_COMMAND_CONFIG = "command_config.json"


def load_config(file_path):
    """Load a JSON config file. Raises with a readable message on failure."""
    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        # The auth config is deliberately not in version control, so a fresh clone
        # will not have one. Say so, rather than leaving a bare traceback.
        example = f"{file_path}.example"
        hint = f" Copy {example} and fill it in." if os.path.exists(example) else ""
        print(f"Config file {file_path} not found.{hint}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"Error loading config file {file_path}: {e}", file=sys.stderr)
        raise


def setup_logging(debug):
    if debug:
        logging.basicConfig(level=logging.DEBUG)
        for name in ("zeep", "zeep.transport", "zeep.client", "zeep.wsdl"):
            logging.getLogger(name).setLevel(logging.DEBUG)


def redact(text, *secrets):
    """Remove secrets from text before it is printed or logged.

    Debug output includes the full SOAP envelope, which carries the password.
    """
    if text is None:
        return None
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "***REDACTED***")
    return text


def parse_params(pairs, params_json=None):
    """Build the parameter dict for an operation.

    ``pairs`` are ``key=value`` strings, split on the FIRST ``=`` only so that
    values containing ``=`` (base64 handles, query strings) survive.

    ``params_json`` is a JSON object merged over the pairs. It is the only way to
    express the complex types the API uses, for example a StringArray:

        {"nameArray": {"items": ["hero", "banner"]}}
    """
    params = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"Parameter {pair!r} is not in key=value form")
        key, value = pair.split("=", 1)
        params[key] = value
    if params_json:
        decoded = json.loads(params_json) if isinstance(params_json, str) else params_json
        if not isinstance(decoded, dict):
            raise ValueError("--params-json must decode to a JSON object")
        params.update(decoded)
    return params


def resolve_endpoints(auth_config, region=None):
    """Return (wsdl_url, service_url).

    An explicit --region wins; otherwise the config's own URLs are used.
    """
    if region:
        key = region.lower()
        if key not in REGIONS:
            raise ValueError(f"Unknown region {region!r}. Known: {', '.join(sorted(REGIONS))}")
        return REGIONS[key]["wsdl_url"], REGIONS[key]["service_url"]
    try:
        return auth_config["wsdl_url"], auth_config["service_url"]
    except KeyError as e:
        raise ValueError(f"auth config is missing {e.args[0]!r}; pass --region instead") from e


def resolve_password(auth_config):
    """Password from SCENE7_PASSWORD if set, otherwise from the config file.

    The environment variable keeps the credential out of any file, which matters
    because auth_config.json sits next to the code.
    """
    return os.environ.get("SCENE7_PASSWORD") or auth_config.get("password")


def create_client(auth_config, region=None, history=None, basic_auth=False):
    """Build a zeep client bound to the service address.

    With basic_auth the credentials go on the HTTP session instead of in a SOAP
    header, which the server accepts equally (see the module docstring).
    """
    wsdl_url, service_url = resolve_endpoints(auth_config, region)
    plugins = [history] if history is not None else []
    settings = Settings(strict=False, xml_huge_tree=True)
    session = requests.Session()
    if basic_auth:
        password = resolve_password(auth_config)
        if not auth_config.get("username") or not password:
            raise ValueError("username and password are required (config or SCENE7_PASSWORD)")
        session.auth = HTTPBasicAuth(auth_config["username"], password)
    client = Client(
        wsdl=wsdl_url,
        transport=Transport(session=session),
        settings=settings,
        plugins=plugins,
    )
    client.service._binding_options["address"] = service_url
    return client


def resolve_auth_header_qname(client):
    """Find the authHeader element that actually authenticates.

    Both the versioned and the unversioned namespace declare an identical-looking
    element; only the versioned one is honoured. The versioned namespace is the
    longer string, being the unversioned one plus a date, so the most specific
    match is the right one for whichever WSDL version is in use.
    """
    candidates = []
    for namespace in client.wsdl.types.namespaces:
        qname = "{%s}%s" % (namespace, AUTH_HEADER_NAME)
        try:
            client.get_element(qname)
        except Exception:
            continue
        candidates.append(namespace)
    if not candidates:
        raise ValueError(f"the WSDL declares no {AUTH_HEADER_NAME} element in any namespace")
    return "{%s}%s" % (max(candidates, key=len), AUTH_HEADER_NAME)


def build_auth_header(client, auth_config):
    """Build the authHeader SOAP header the IPS API requires.

    appName is mandatory in the versioned element. Leaving it out fails zeep's own
    validation, which is the one helpful error in this area.
    """
    password = resolve_password(auth_config)
    if not auth_config.get("username") or not password:
        raise ValueError("username and password are required (config or SCENE7_PASSWORD)")
    auth_header_type = client.get_element(resolve_auth_header_qname(client))
    return auth_header_type(
        user=auth_config["username"],
        password=password,
        appName=APP_NAME,
        appVersion=APP_VERSION,
        # Ask for faults as HTTP 200 with a fault body, which zeep parses cleanly.
        faultHttpStatusCode=200,
    )


def execute_command(client, command, auth_header):
    """Invoke one operation by name, passing the auth header."""
    command_name = command["name"]
    params = command.get("params") or {}
    method = getattr(client.service, command_name, None)
    if method is None:
        raise ValueError(f"Operation {command_name!r} is not in the service")
    if auth_header is None:
        return method(**params)
    return method(**params, _soapheaders=[auth_header])


def list_available_methods(client):
    print("Available Services:")
    for service in client.wsdl.services.values():
        print(f"Service: {service.name}")
        for port in service.ports.values():
            print(f"  Port: {port.name}")
            for operation in sorted(port.binding._operations.values(), key=lambda op: op.name):
                print(f"    Operation: {operation.name}")


def _json_default(value):
    """Serialise the types zeep returns that json does not handle."""
    for attr in ("isoformat",):
        if hasattr(value, attr):
            return getattr(value, attr)()
    return str(value)


def format_response(response, as_json):
    if as_json:
        return json.dumps(serialize_object(response), indent=2, default=_json_default)
    return str(response)


def print_history(history, *secrets):
    """Print the last exchange, with secrets removed."""
    for label, item in (("request", getattr(history, "last_sent", None)),
                        ("response", getattr(history, "last_received", None))):
        if not item:
            continue
        envelope = item.get("envelope") if isinstance(item, dict) else None
        if envelope is None:
            continue
        xml = etree.tostring(envelope, pretty_print=True).decode()
        print(f"--- {label} ---")
        print(redact(xml, *secrets))


def parse_command_line_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Scene7 / Dynamic Media IPS API client",
        epilog=(
            "Examples:\n"
            "  scene7api.py --method getCompanyInfo --params companyName=ExampleCo\n"
            "  scene7api.py --method getAssetsByName \\\n"
            "      --params-json '{\"companyHandle\":\"c|12345\","
            "\"nameArray\":{\"items\":[\"hero\"]}}'\n\n"
            "Flat key=value parameters cover simple operations. Operations taking arrays or\n"
            "nested types need --params-json.\n\n"
            "The password may be supplied in SCENE7_PASSWORD instead of the config file.\n"
            "If the SOAP header is refused, --auth-mode basic is the shorter path."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--method", type=str, help="API operation to call")
    parser.add_argument("--params", type=str, nargs="*",
                        help="key=value pairs (split on the first = only)")
    parser.add_argument("--params-json", type=str,
                        help="JSON object of parameters, merged over --params")
    parser.add_argument("--auth-config", type=str, default=DEFAULT_AUTH_CONFIG,
                        help=f"path to the auth config (default: {DEFAULT_AUTH_CONFIG})")
    parser.add_argument("--command-config", type=str, default=DEFAULT_COMMAND_CONFIG,
                        help=f"path to the command config (default: {DEFAULT_COMMAND_CONFIG})")
    parser.add_argument("--region", type=str, choices=sorted(REGIONS),
                        help="override the endpoints with a known region")
    parser.add_argument("--auth-mode", choices=("soap", "basic"), default="soap",
                        help="send credentials in the SOAP authHeader (default) or as HTTP Basic")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="print the response as JSON")
    parser.add_argument("--list-methods", action="store_true",
                        help="list every operation the WSDL exposes, then exit")
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    command = {}
    if args.method:
        command["name"] = args.method
        command["params"] = parse_params(args.params, args.params_json)
    return command, args


def main(argv=None):
    command_line_command, args = parse_command_line_args(argv)
    setup_logging(args.debug)

    auth_config = load_config(args.auth_config)
    password = resolve_password(auth_config)

    basic_auth = args.auth_mode == "basic"
    history = HistoryPlugin()
    client = create_client(auth_config, region=args.region, history=history, basic_auth=basic_auth)

    if args.list_methods:
        list_available_methods(client)
        return 0

    if command_line_command.get("name"):
        commands = [command_line_command]
    else:
        commands = load_config(args.command_config)["commands"]

    auth_header = None if basic_auth else build_auth_header(client, auth_config)

    exit_code = 0
    for command in commands:
        try:
            response = execute_command(client, command, auth_header)
            print(format_response(response, args.as_json))
        except Exception as e:
            print(redact(f"Error executing {command['name']}: {e}", password), file=sys.stderr)
            exit_code = 1
        finally:
            if args.debug:
                print_history(history, password)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
