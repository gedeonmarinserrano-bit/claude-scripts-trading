"""Obtiene o renueva el access token OAuth de la cTrader Open API.

Uso:
    python -m ctrader_mcp.auth login   --client-id ID --client-secret SECRET [--redirect-uri URI]
    python -m ctrader_mcp.auth refresh --client-id ID --client-secret SECRET --refresh-token TOKEN
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTH_URI = "https://openapi.ctrader.com/apps/auth"
TOKEN_URI = "https://openapi.ctrader.com/apps/token"


def auth_url(client_id, redirect_uri, scope="trading"):
    query = urllib.parse.urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "scope": scope})
    return f"{AUTH_URI}?{query}"


def _token_request(params):
    with urllib.request.urlopen(f"{TOKEN_URI}?{urllib.parse.urlencode(params)}", timeout=30) as resp:
        return json.load(resp)


def exchange_code(code, client_id, client_secret, redirect_uri):
    return _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                           "client_id": client_id, "client_secret": client_secret})


def refresh(refresh_token, client_id, client_secret):
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token,
                           "client_id": client_id, "client_secret": client_secret})


def wait_for_code(redirect_uri):
    parsed = urllib.parse.urlparse(redirect_uri)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result["code"] = (query.get("code") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Autorización recibida, ya puedes cerrar esta pestaña.".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer((parsed.hostname or "localhost", parsed.port or 80), Handler)
    while "code" not in result:
        server.handle_request()
    server.server_close()
    return result["code"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["login", "refresh"])
    parser.add_argument("--client-id", default=os.environ.get("CTRADER_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("CTRADER_CLIENT_SECRET"))
    parser.add_argument("--redirect-uri", default="http://localhost:8765/callback")
    parser.add_argument("--refresh-token", default=os.environ.get("CTRADER_REFRESH_TOKEN"))
    parser.add_argument("--no-browser", action="store_true",
                        help="no abrir el navegador ni escuchar; pega el code a mano")
    args = parser.parse_args(argv)
    if not args.client_id or not args.client_secret:
        parser.error("se necesitan --client-id y --client-secret (o CTRADER_CLIENT_ID/CTRADER_CLIENT_SECRET)")

    if args.command == "refresh":
        if not args.refresh_token:
            parser.error("se necesita --refresh-token")
        tokens = refresh(args.refresh_token, args.client_id, args.client_secret)
    else:
        url = auth_url(args.client_id, args.redirect_uri)
        print(f"Abre esta URL y autoriza tus cuentas:\n\n  {url}\n")
        if args.no_browser:
            code = input("Pega el parámetro 'code' de la URL de redirección: ").strip()
        else:
            webbrowser.open(url)
            print(f"Esperando la redirección en {args.redirect_uri} ...")
            code = wait_for_code(args.redirect_uri)
        tokens = exchange_code(code, args.client_id, args.client_secret, args.redirect_uri)

    print(json.dumps(tokens, indent=2))
    if tokens.get("accessToken"):
        print(f"\nCTRADER_ACCESS_TOKEN={tokens['accessToken']}")
        print(f"CTRADER_REFRESH_TOKEN={tokens.get('refreshToken', '')}")


if __name__ == "__main__":
    main()
