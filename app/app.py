"""
CropGuard — entry point.
Run: python app/app.py
Then open: http://localhost:8050
"""
import sys
from pathlib import Path

import dash
import dash_bootstrap_components as dbc

sys.path.insert(0, str(Path(__file__).parent.parent))

from layout import build_layout
from callbacks import register_callbacks

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap",
    ],
    title="CropGuard | Sayariy-Resurgiendo",
    suppress_callback_exceptions=True,
)

app.layout = build_layout()
register_callbacks(app)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
