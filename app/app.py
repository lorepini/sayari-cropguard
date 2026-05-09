"""
CropGuard — entry point.
Run: python app/app.py
Then open: http://localhost:8050
"""
import sys
from pathlib import Path

import dash
import dash_bootstrap_components as dbc
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from layout import build_layout
from callbacks import register_callbacks
from pozos_callbacks import register_pozos_callbacks
from sencilla_callbacks import register_sencilla_callbacks
from src.auth import register_auth_routes
from api import api_bp

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap",
    ],
    title="CropGuard | Sayariy-Resurgiendo",
    suppress_callback_exceptions=True,
)

# Sign Flask session cookies so /login can persist `can_write` per browser.
app.server.secret_key = config.CROPGUARD_SECRET_KEY
register_auth_routes(app.server)

# REST API — allow the Lovable React frontend to call us cross-origin
app.server.register_blueprint(api_bp)
CORS(app.server, resources={r"/api/*": {"origins": "*"}})

app.layout = build_layout()
register_callbacks(app)
register_pozos_callbacks(app)
register_sencilla_callbacks(app)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8051))
    debug = os.environ.get("RENDER") is None
    app.run(debug=debug, host="0.0.0.0", port=port)
