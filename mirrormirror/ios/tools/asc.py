#!/usr/bin/env python3
"""App Store Connect API helper for releasing Mirror Mirror from a GitHub Actions runner, with no Xcode login.

    asc.py selftest             offline check of the token and report code against a mock server (no credentials, no network)
    asc.py preflight            read-only: proves the key works and shows what already exists for this app
    asc.py register-bundle-id   registers the app's bundle id in the developer portal (the one write in this file)

Credentials come from the environment and are never printed:
    ASC_KEY_ID      the API key id
    ASC_ISSUER_ID   the issuer id shown beside the keys
    ASC_KEY_P8      the AuthKey_XXXX.p8 text, or the same text base64-encoded

Actions logs of a public repository are public, so this prints counts and states only: no tokens, no names of other apps and
no contact details. Creating the app record itself has no API; it is the one step done in the App Store Connect website.
"""

import base64
import collections
import contextlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import jwt
except ImportError:
    sys.exit('PyJWT is missing. Run: python -m pip install "pyjwt[crypto]"')

API_BASE = os.environ.get("ASC_API_BASE", "https://api.appstoreconnect.apple.com")
PBXPROJ = Path(__file__).resolve().parents[1] / "MirrorMirror.xcodeproj" / "project.pbxproj"
APP_NAME = "Mirror Mirror on The Wall"
RETRY_STATUSES = (429, 500, 502, 503, 504)


def die(message, code=1):
    print(message, flush=True)
    sys.exit(code)


def project_bundle_id():
    ids = set(re.findall(r"PRODUCT_BUNDLE_IDENTIFIER = ([A-Za-z0-9.\-]+);", PBXPROJ.read_text()))
    if len(ids) != 1:
        die(f"expected exactly one bundle id in the Xcode project, found {sorted(ids)}")
    return ids.pop()


def load_credentials():
    key_id = os.environ.get("ASC_KEY_ID", "").strip()
    issuer = os.environ.get("ASC_ISSUER_ID", "").strip()
    key = os.environ.get("ASC_KEY_P8", "").strip()
    missing = [n for n, v in (("ASC_KEY_ID", key_id), ("ASC_ISSUER_ID", issuer), ("ASC_KEY_P8", key)) if not v]
    if missing:
        die("These repository secrets are not set: " + ", ".join(missing) + ". See the Cloud route in mirrormirror/ios/PUBLISH.md.", 2)
    if "BEGIN" not in key:
        try:
            key = base64.b64decode(key).decode()
        except ValueError:
            key = ""
    key = key.replace("\r\n", "\n")
    if "BEGIN PRIVATE KEY" not in key:
        die("ASC_KEY_P8 is set but does not look like a .p8 file. It should start with -----BEGIN PRIVATE KEY-----.", 2)
    return key_id, issuer, key


def make_token(key_id, issuer, private_key):
    now = int(time.time())
    claims = {"iss": issuer, "iat": now, "exp": now + 15 * 60, "aud": "appstoreconnect-v1"}
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"})


def parse(raw):
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def explain(payload):
    errors = payload.get("errors", []) if isinstance(payload, dict) else []
    return "; ".join(f"{e.get('code', '?')}: {e.get('title', '')} {e.get('detail', '')}".strip() for e in errors) or "no detail"


class Api:
    def __init__(self, token):
        self.token = token

    def call(self, method, path, params=None, body=None):
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe="[],")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(4):
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.status, parse(response.read())
            except urllib.error.HTTPError as err:
                if err.code in RETRY_STATUSES and attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return err.code, parse(err.read())
            except urllib.error.URLError as err:
                if attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                die(f"could not reach App Store Connect: {err.reason}")


def count_by(items, attribute):
    counts = collections.Counter(i.get("attributes", {}).get(attribute, "?") for i in items)
    return ", ".join(f"{name} {n}" for name, n in sorted(counts.items())) or "none"


def find_bundle_id(api, bundle_id):
    status, payload = api.call("GET", "/v1/bundleIds", {"filter[identifier]": bundle_id, "limit": 200})
    if status in (401, 403):
        die(f"App Store Connect refused the key (HTTP {status}): {explain(payload)}\n"
            "Check that the key is Active and that ASC_KEY_ID and ASC_ISSUER_ID belong to it.")
    if status != 200:
        die(f"unexpected answer from App Store Connect (HTTP {status}): {explain(payload)}")
    return any(i.get("attributes", {}).get("identifier") == bundle_id for i in payload.get("data", []))


def preflight(api):
    bundle_id = project_bundle_id()
    registered = find_bundle_id(api, bundle_id)
    print("key accepted by App Store Connect: yes")
    print(f"bundle id {bundle_id} registered in the developer portal: {'yes' if registered else 'no'}")

    status, payload = api.call("GET", "/v1/apps", {"filter[bundleId]": bundle_id, "limit": 5})
    has_record = status == 200 and bool(payload.get("data"))
    print(f"app record in App Store Connect for that bundle id: {'yes' if has_record else 'no' if status == 200 else f'unknown (HTTP {status})'}")

    status, payload = api.call("GET", "/v1/devices", {"limit": 200, "filter[status]": "ENABLED", "fields[devices]": "deviceClass,status"})
    if status == 200:
        print("registered devices: " + count_by(payload.get("data", []), "deviceClass") + "  (automatic development signing needs at least one)")
    else:
        print(f"registered devices: not readable with this key (HTTP {status})")

    status, payload = api.call("GET", "/v1/certificates", {"limit": 200, "fields[certificates]": "certificateType"})
    if status == 200:
        print("signing certificates by type: " + count_by(payload.get("data", []), "certificateType"))
    else:
        print(f"signing certificates: not readable with this key (HTTP {status}); cloud signing needs the Admin role")

    if not registered:
        print("next: run register-bundle-id")
    elif not has_record:
        print("next: create the app record in the App Store Connect website, then upload the build")
    else:
        print("next: upload the build")


def register_bundle_id(api):
    bundle_id = project_bundle_id()
    if find_bundle_id(api, bundle_id):
        print(f"{bundle_id} is already registered; nothing to do")
        return
    body = {"data": {"type": "bundleIds", "attributes": {"identifier": bundle_id, "name": APP_NAME, "platform": "IOS"}}}
    status, payload = api.call("POST", "/v1/bundleIds", body=body)
    if status != 201:
        die(f"could not register {bundle_id} (HTTP {status}): {explain(payload)}")
    print(f"registered {bundle_id} for iOS")
    print("next: App Store Connect > Apps > New App, pick that bundle id from the list")


COMMANDS = {"preflight": preflight, "register-bundle-id": register_bundle_id}


# ---- offline self test -------------------------------------------------------------------------------------------------------


class MockAppStoreConnect(BaseHTTPRequestHandler):
    registered = False
    deny = False
    seen = []

    def log_message(self, *args):
        pass

    def reply(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        cls = type(self)
        cls.seen.append(("GET", self.path, self.headers.get("Authorization", "")[:7]))
        if cls.deny:
            return self.reply(401, {"errors": [{"code": "NOT_AUTHORIZED", "title": "Authentication credentials are missing or invalid."}]})
        path = urllib.parse.urlparse(self.path).path
        row = {"type": "bundleIds", "id": "B1", "attributes": {"identifier": "com.grandviewventures.mirrormirror", "platform": "IOS"}}
        data = {
            "/v1/bundleIds": [row] if cls.registered else [],
            "/v1/apps": [],
            "/v1/devices": [{"attributes": {"deviceClass": "IPHONE"}}, {"attributes": {"deviceClass": "IPAD"}}],
            "/v1/certificates": [{"attributes": {"certificateType": t}} for t in ("DEVELOPMENT", "DISTRIBUTION", "DEVELOPMENT")],
        }[path]
        self.reply(200, {"data": data})

    def do_POST(self):
        cls = type(self)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        cls.seen.append(("POST", self.path, body))
        cls.registered = True
        self.reply(201, {"data": {"type": "bundleIds", "id": "B1", "attributes": body["data"]["attributes"]}})


def run_captured(function, *args):
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out):
        try:
            function(*args)
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue()


def selftest():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    global API_BASE
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()

    token = make_token("TESTKEY123", "11111111-2222-3333-4444-555555555555", pem)
    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, key.public_key(), algorithms=["ES256"], audience="appstoreconnect-v1")
    assert header["kid"] == "TESTKEY123" and header["alg"] == "ES256", header
    assert claims["iss"] == "11111111-2222-3333-4444-555555555555" and claims["exp"] - claims["iat"] <= 20 * 60, claims
    print("token: header, claims and signature check out")

    saved = {k: os.environ.pop(k, None) for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_P8")}
    try:
        code, out = run_captured(load_credentials)
        assert code == 2 and "ASC_KEY_P8" in out, (code, out)
        os.environ.update(ASC_KEY_ID="TESTKEY123", ASC_ISSUER_ID="iss", ASC_KEY_P8="not a key")
        code, out = run_captured(load_credentials)
        assert code == 2 and "does not look like" in out, (code, out)
        os.environ["ASC_KEY_P8"] = base64.b64encode(pem.encode()).decode()
        assert load_credentials()[2].startswith("-----BEGIN PRIVATE KEY-----")
        os.environ["ASC_KEY_P8"] = pem.replace("\n", "\r\n")
        assert "\r" not in load_credentials()[2]
    finally:
        for name, value in saved.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value
    print("credentials: missing, malformed, base64 and CRLF forms handled")

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockAppStoreConnect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    API_BASE = f"http://127.0.0.1:{server.server_address[1]}"
    api = Api(token)
    try:
        code, out = run_captured(preflight, api)
        assert code == 0, out
        for expected in ("key accepted by App Store Connect: yes", "registered in the developer portal: no",
                         "for that bundle id: no", "registered devices: IPAD 1, IPHONE 1",
                         "DEVELOPMENT 2, DISTRIBUTION 1", "next: run register-bundle-id"):
            assert expected in out, (expected, out)
        assert token not in out
        assert any("filter[identifier]=com.grandviewventures.mirrormirror" in str(s[1]) for s in MockAppStoreConnect.seen)
        assert all(s[2] == "Bearer " for s in MockAppStoreConnect.seen if s[0] == "GET")

        code, out = run_captured(register_bundle_id, api)
        assert code == 0 and "registered com.grandviewventures.mirrormirror for iOS" in out, (code, out)
        post = [s for s in MockAppStoreConnect.seen if s[0] == "POST"][0]
        assert post[2]["data"]["attributes"] == {"identifier": "com.grandviewventures.mirrormirror", "name": APP_NAME, "platform": "IOS"}, post

        code, out = run_captured(register_bundle_id, api)
        assert code == 0 and "already registered" in out and len([s for s in MockAppStoreConnect.seen if s[0] == "POST"]) == 1, out
        code, out = run_captured(preflight, api)
        assert "registered in the developer portal: yes" in out and "next: create the app record" in out, out

        MockAppStoreConnect.deny = True
        code, out = run_captured(preflight, api)
        assert code == 1 and "refused the key (HTTP 401)" in out and "NOT_AUTHORIZED" in out, (code, out)
    finally:
        server.shutdown()
    print("preflight and register-bundle-id: behave correctly against a mock App Store Connect, including a refused key")
    print("selftest passed")


def main(argv):
    if len(argv) != 2 or argv[1] not in {"selftest", *COMMANDS}:
        die("usage: asc.py selftest | " + " | ".join(COMMANDS), 2)
    if argv[1] == "selftest":
        return selftest()
    key_id, issuer, private_key = load_credentials()
    COMMANDS[argv[1]](Api(make_token(key_id, issuer, private_key)))


if __name__ == "__main__":
    main(sys.argv)
