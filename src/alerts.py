"""
LLM-powered alert generation in Spanish.
Uses Claude Haiku via the Anthropic API.
Falls back to a rule-based template if no API key is set.
"""
import os
from datetime import date

import config


def _template_alert(community: str, ndvi: float, stress_prob: float,
                    status: str, ndwi: float | None = None) -> str:
    """Deterministic Spanish alert — used when no API key is available."""
    level_map = {
        "alert":   "⚠️ ALERTA",
        "watch":   "🟡 VIGILANCIA",
        "healthy": "✅ NORMAL",
        "no_data": "⚪ SIN DATOS",
    }
    tag = level_map.get(status, "⚪ DESCONOCIDO")
    ndvi_str = f"{ndvi:.2f}" if ndvi == ndvi else "N/D"  # nan check
    prob_str = f"{stress_prob * 100:.0f}%" if stress_prob == stress_prob else "N/D"

    msgs = {
        "alert": (
            f"{tag} — {community}: el índice de vegetación NDVI ha caído a {ndvi_str}, "
            f"lo que indica estrés hídrico o de nutrientes con probabilidad del {prob_str}. "
            "Se recomienda visita de campo esta semana."
        ),
        "watch": (
            f"{tag} — {community}: NDVI en {ndvi_str} muestra una tendencia a la baja "
            f"(probabilidad de estrés: {prob_str}). "
            "Monitorear en los próximos 5 días."
        ),
        "healthy": (
            f"{tag} — {community}: cultivos en buen estado (NDVI {ndvi_str}). "
            "No se requiere acción inmediata."
        ),
        "no_data": (
            f"{tag} — {community}: sin datos satelitales disponibles para esta semana "
            "(posible cobertura nubosa). Se actualizará en el próximo paso."
        ),
    }
    return msgs.get(status, f"{tag} — {community}: estado desconocido.")


def generate_alert(
    community: str,
    ndvi: float,
    stress_prob: float,
    status: str,
    ndwi: float | None = None,
    trend: float | None = None,
    observation_date: str | None = None,
) -> str:
    """
    Generate a 2–3 sentence Spanish alert for NGO staff.

    Uses Claude Haiku if ANTHROPIC_API_KEY is set,
    otherwise falls back to rule-based template.
    """
    if observation_date is None:
        observation_date = date.today().isoformat()

    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        return _template_alert(community, ndvi, stress_prob, status, ndwi)

    try:
        import anthropic

        ndvi_str = f"{ndvi:.3f}" if ndvi == ndvi else "no disponible"
        ndwi_str = f"{ndwi:.3f}" if ndwi is not None and ndwi == ndwi else "no disponible"
        trend_str = (
            f"{'disminuyendo' if trend < 0 else 'aumentando'} ({trend:+.3f} en 14 días)"
            if trend is not None else "desconocida"
        )
        prob_str = f"{stress_prob * 100:.0f}%" if stress_prob == stress_prob else "desconocida"

        prompt = f"""Eres un asistente técnico de la ONG Sayariy-Resurgiendo en Perú.
Escribe un mensaje de alerta conciso (2-3 oraciones) en español claro y accesible
para el equipo de campo (no son expertos técnicos).

Datos del satélite Sentinel-2 para la comunidad {community}:
- Fecha de observación: {observation_date}
- NDVI (salud del cultivo): {ndvi_str}  [saludable > 0.55, alerta < 0.35]
- NDWI (humedad de la planta): {ndwi_str}
- Tendencia NDVI: {trend_str}
- Probabilidad de estrés calculada: {prob_str}
- Estado: {status.upper()}

El mensaje debe: (1) indicar el nivel de urgencia, (2) explicar en términos simples
qué está pasando con los cultivos, (3) sugerir una acción concreta si es necesario.
Responde SOLO con el mensaje, sin introducción."""

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=config.MAX_ALERT_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except Exception as e:
        print(f"[alerts] LLM failed ({e}), using template.")
        return _template_alert(community, ndvi, stress_prob, status, ndwi)


def generate_all_alerts(scored_gdf) -> dict[str, str]:
    """
    Generate alerts for all communities in a scored GeoDataFrame.
    Returns {community_name: alert_text}.
    """
    alerts = {}
    for _, row in scored_gdf.iterrows():
        name    = row.get("name", row.get("community", "Desconocida"))
        ndvi    = row.get("NDVI", float("nan"))
        stress  = row.get("stress_prob", float("nan"))
        status  = row.get("status", "no_data")
        ndwi    = row.get("NDWI", None)
        trend   = row.get("NDVI_trend", None)

        alerts[name] = generate_alert(
            community=name,
            ndvi=ndvi,
            stress_prob=stress,
            status=status,
            ndwi=ndwi,
            trend=trend,
        )
    return alerts
