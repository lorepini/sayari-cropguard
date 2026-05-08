"""
Minimal shared-password auth gate for CropGuard write actions.

The dashboard is publicly deployed on Render — read views must remain open to
anyone, but the manual well-measurement form should only accept submissions
from someone who knows the NGO's shared password. We use Flask's signed
session cookie to remember the auth state per browser.

There are no user accounts. One password (CROPGUARD_WRITE_PASSWORD) lets you
write; everyone else can still browse. On success we set
``session['can_write'] = True``; ``/logout`` clears it.
"""
from __future__ import annotations

from flask import Flask, redirect, request, session

import config


_LOGIN_PAGE_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>CropGuard — Iniciar sesión</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      height: 100%;
      background-color: #1A2744;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      color: #FFFFFF;
    }}
    .wrap {{
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .card {{
      background-color: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      padding: 32px 28px;
      width: 100%;
      max-width: 360px;
      box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
    }}
    h1 {{
      margin: 0 0 6px 0;
      font-size: 1.25rem;
      font-weight: 700;
    }}
    p.sub {{
      margin: 0 0 20px 0;
      font-size: 0.85rem;
      color: rgba(255, 255, 255, 0.7);
    }}
    label {{
      display: block;
      font-size: 0.78rem;
      font-weight: 600;
      color: rgba(255, 255, 255, 0.85);
      margin-bottom: 6px;
    }}
    input[type="password"] {{
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      border-radius: 6px;
      border: 1px solid rgba(255, 255, 255, 0.2);
      background-color: rgba(255, 255, 255, 0.08);
      color: #FFFFFF;
      font-size: 0.95rem;
      margin-bottom: 16px;
    }}
    input[type="password"]:focus {{
      outline: none;
      border-color: #00897B;
      background-color: rgba(255, 255, 255, 0.12);
    }}
    button {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 6px;
      border: 0;
      background-color: #00897B;
      color: #FFFFFF;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
    }}
    button:hover {{
      background-color: #00A693;
    }}
    .error {{
      background-color: rgba(231, 76, 60, 0.18);
      border: 1px solid rgba(231, 76, 60, 0.45);
      color: #FFBFB7;
      padding: 8px 10px;
      border-radius: 6px;
      font-size: 0.82rem;
      margin-bottom: 14px;
    }}
    a.back {{
      display: block;
      text-align: center;
      margin-top: 14px;
      font-size: 0.78rem;
      color: rgba(255, 255, 255, 0.6);
      text-decoration: none;
    }}
    a.back:hover {{ color: #FFFFFF; }}
  </style>
</head>
<body>
  <div class="wrap">
    <form class="card" method="POST" action="/login">
      <h1>CropGuard</h1>
      <p class="sub">Inicie sesión con la contraseña de la NGO para registrar mediciones.</p>
      {error_block}
      <label for="password">Contraseña</label>
      <input type="password" id="password" name="password" autofocus required>
      <button type="submit">Entrar</button>
      <a class="back" href="/">Volver al panel</a>
    </form>
  </div>
</body>
</html>
"""


def _render_login_page(error: str | None = None) -> str:
    error_block = (
        f'<div class="error">{error}</div>' if error else ""
    )
    return _LOGIN_PAGE_TEMPLATE.format(error_block=error_block)


def is_authed() -> bool:
    """Return True if the current request's session is allowed to write."""
    return bool(session.get("can_write"))


def register_auth_routes(app: Flask) -> None:
    """Wire ``/login`` (GET + POST) and ``/logout`` onto the Flask server.

    Idempotent: safe to call once on Dash boot.
    """

    @app.route("/login", methods=["GET", "POST"])
    def login():  # noqa: D401 - Flask view
        if request.method == "POST":
            submitted = request.form.get("password", "")
            expected = config.CROPGUARD_WRITE_PASSWORD
            if expected and submitted == expected:
                session["can_write"] = True
                return redirect("/")
            return _render_login_page(error="Contraseña incorrecta"), 401
        return _render_login_page()

    @app.route("/logout", methods=["GET", "POST"])
    def logout():  # noqa: D401 - Flask view
        session.pop("can_write", None)
        return redirect("/login")
