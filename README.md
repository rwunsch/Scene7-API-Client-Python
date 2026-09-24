# Scene7 API Client

A Python client for Adobe's [Scene7 IPS Web Service](https://experienceleague.adobe.com/en/docs/dynamic-media-developer-resources/image-production-api/c-wsdl-versions), the SOAP API behind Dynamic Media Classic.

It is a thin generic dispatcher over the WSDL: every operation the WSDL exposes is callable without per-operation code. Against the 2014-04-03 WSDL that is 328 operations. Calls can be given on the command line or in `command_config.json`; command-line arguments win.

## Authentication, and the fault that wastes an afternoon

`authHeader` is declared in **two** namespaces and only one of them authenticates. The server honours the header in the **versioned** namespace that the operations themselves use (for the 2014-04-03 WSDL, `.../IpsApi/xsd/2014-04-03`). The same header in the unversioned `.../IpsApi/xsd` passes schema validation, is rendered onto the wire, and is then ignored:

```
authenticationFault 10000
No authentication credentials found in SOAP header or HTTP Basic header
```

That message says no credentials were sent while the credentials are plainly visible in the request envelope, which sends you looking at TLS, proxies and entitlements rather than at the namespace. The versioned element also requires `appName`; leaving it out fails zeep's own validation, which is at least an honest error.

Measured against the EMEA endpoint on 2026-09-24:

| Header form | Result |
|---|---|
| Unversioned namespace, no `appName` | fault 10000, no credentials found |
| Unversioned namespace, with `appName` | fault 10000, no credentials found |
| Versioned namespace, no `appName` | zeep `ValidationError`, `appName` required |
| **Versioned namespace, with `appName`** | **success** |
| **HTTP Basic, no SOAP header** | **success** |

The client resolves the namespace from the WSDL rather than hardcoding a date, so a newer WSDL version is followed automatically.

Both modes work. The SOAP header is the default, because it is what the WSDL declares and it carries `locale` and `gzipResponse` alongside the credentials. `--auth-mode basic` is the shorter path when the header is being awkward.

## Prerequisites

Python 3.x, plus:

```bash
pip install zeep requests lxml
```

## Configuration

### auth_config.json

Not in version control. Copy the example and fill it in:

```bash
cp client/auth_config.json.example client/auth_config.json
```

```json
{
    "username": "you@example.com",
    "password": "",
    "wsdl_url": "https://s7sps3apissl.scene7.com/scene7/webservice/IpsApi-2014-04-03.wsdl",
    "service_url": "https://s7sps3apissl.scene7.com/scene7/services/IpsApiService",
    "debug": false
}
```

**Prefer the environment variable for the password**, so the credential is never in a file:

```bash
export SCENE7_PASSWORD='...'
```

`SCENE7_PASSWORD` overrides `password` in the config. `--region` overrides `wsdl_url` and `service_url`, so with it the config needs only a username.

### Regional endpoints

| Region | Endpoint |
|---|---|
| `na` | `s7sps1apissl.scene7.com` |
| `emea` | `s7sps3apissl.scene7.com` |
| `apac` | `s7sps5apissl.scene7.com` |

These are the endpoints AEM itself publishes at `/libs/settings/dam/scene7/endpoints`. Calling the wrong region for a company returns an authentication fault, not a redirect.

### command_config.json

Used when no `--method` is given:

```json
{
    "commands": [
        { "name": "getCompanyInfo", "params": { "companyName": "ExampleCo" } }
    ]
}
```

## Usage

```bash
# simple, flat parameters
python3 client/scene7api.py --method getCompanyInfo --params companyName=ExampleCo

# pick a region rather than editing the config
python3 client/scene7api.py --region emea --method getCompanyInfo --params companyName=ExampleCo

# complex parameters: arrays and nested types need JSON
python3 client/scene7api.py --method getAssetsByName \
    --params-json '{"companyHandle":"c|12345","nameArray":{"items":["hero","banner"]}}'

# machine-readable output
python3 client/scene7api.py --method getCompanyInfo --params companyName=ExampleCo --json

# what can I call?
python3 client/scene7api.py --list-methods

# credentials on the HTTP session instead of in the envelope
python3 client/scene7api.py --auth-mode basic --method getCompanyInfo --params companyName=ExampleCo
```

### Arguments

| Argument | Purpose |
|---|---|
| `--method` | Operation to call |
| `--params` | `key=value` pairs, split on the **first** `=` only, so handles and base64 values survive |
| `--params-json` | JSON object merged over `--params`; the only way to express arrays and nested types |
| `--auth-config` | Path to the auth config (default `auth_config.json`) |
| `--command-config` | Path to the command config (default `command_config.json`) |
| `--region` | `na`, `emea` or `apac`; overrides the config endpoints |
| `--auth-mode` | `soap` (default) or `basic` |
| `--json` | Print the response as JSON |
| `--list-methods` | List every operation the WSDL exposes, then exit |
| `--debug` | Log the SOAP exchange, with the password redacted |

`--debug` prints the full request and response envelopes. The password is replaced with `***REDACTED***` in anything the client prints, including error messages, which can otherwise quote the arguments back.

The exit code is 0 when every command succeeded and 1 when any failed, so the client can be used in a shell pipeline.

## Tests

```bash
python3 -m pytest tests -q
```

68 tests, no network access: the SOAP client is faked, because the mistakes worth guarding against are about the shape of the call rather than about what the server says back. The suite has been checked by mutation, that is, by reintroducing each bug and confirming the intended test fails.

## Demo video

`demo/scene7api.mp4` shows the earlier version in use.

## Contributing

Pull requests and issues are welcome.

## License

MIT. See [LICENSE](LICENSE).
