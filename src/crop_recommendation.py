"""
ENSO- and season-aware crop recommendations for the Sayariy parcel.

Logic is grounded in three sources:
  1. French et al. (2023, PLOS ONE) — 2017 Coastal El Niño crop impact data
     by category: high-value export fruits (mango, avocado) were resilient
     (+1–2%), while rice (-1.6%), sugarcane (-4.4%), and lemon (-37.9%)
     contracted. Maracuyá (passion fruit) is a high-value tropical export
     vine — resilient to mild ENSO, but flood-sensitive at root level.
  2. INIA / Schoff & Sayan (1969) — Cayaltí-Zaña soils are alluvial sandy
     loam, documented salinisation risk in lower valley sectors, and shallow
     water table susceptibility to drawdown from dense competing wells.
  3. FAO-56 (Allen et al. 1998) / IMARPE ICEN — Peru coastal ENSO index
     drives flooding risk Jan-Mar; drought risk in La Niña years.

Geographic context:
  Sayariy parcel (~13 ha, Cayaltí coastal plain, ~50 m a.s.l.):
  - Maracuyá zone: 3 ha, 3,500 plants (trellised vine, drip irrigated)
  - Huertos: 10 ha across 20 plots (mixed orchard: mango, palta, naranja,
    mandarina, limón, papaya, coco, tuna, algodón — planted Jan 2023)
  - Rotation strip: residual area for frijol/maíz quarterly rotation
  Per-chacra geometry is not yet available — recommendations are parcel-level
  until NGO provides GPS boundaries per plot.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

Severity = Literal["green", "yellow", "red"]

# ── Crop risk profiles ────────────────────────────────────────────────────────
# flood_risk: how badly the crop suffers from waterlogging (high = avoids)
# drought_risk: sensitivity to deficit irrigation / dry spells
# salinity_risk: sensitivity to rising soil electrical conductivity
# el_nino_resilience: based on French et al. (2023) — high means 2017 type
#   events historically did NOT reduce yields significantly
_PROFILES: dict[str, dict] = {
    "maracuya": {
        "name_es": "Maracuyá",
        "flood_risk": "high",       # root rot / Fusarium under waterlogging
        "drought_risk": "medium",
        "salinity_risk": "medium",
        "heat_risk": "low",         # tolerates 30-35 °C well
        "el_nino_resilience": "medium",
        "cycle": "perennial",
        "peak_harvest_months": [6, 7, 8, 9],  # dry season peak
        "avoid_planting_months": [11, 12, 1, 2, 3],  # El Niño flood season
    },
    "huertos_mango": {
        "name_es": "Mango",
        "flood_risk": "medium",
        "drought_risk": "low",      # drought-tolerant once established
        "salinity_risk": "medium",
        "heat_risk": "low",
        "el_nino_resilience": "high",   # French et al. 2023: mango +1.9%
        "cycle": "perennial",
        "peak_harvest_months": [11, 12, 1, 2],
        "avoid_planting_months": [],
    },
    "huertos_palta": {
        "name_es": "Palta (aguacate)",
        "flood_risk": "very_high",  # most flood-sensitive crop in the mix
        "drought_risk": "medium",
        "salinity_risk": "high",
        "heat_risk": "medium",      # heat reduces set above 35 °C
        "el_nino_resilience": "high",   # French et al. 2023: avocado +2.5%
        "cycle": "perennial",
        "peak_harvest_months": [4, 5, 6, 7],
        "avoid_planting_months": [11, 12, 1, 2, 3],
    },
    "frijol": {
        "name_es": "Frijol",
        "flood_risk": "medium",
        "drought_risk": "medium",
        "salinity_risk": "medium",
        "heat_risk": "medium",
        "el_nino_resilience": "medium",
        "cycle": "quarterly",       # 90-day rotation
        "best_planting_months": [4, 5, 6],   # dry season
        "avoid_planting_months": [11, 12, 1],
    },
    "maiz": {
        "name_es": "Maíz",
        "flood_risk": "medium",
        "drought_risk": "medium",
        "salinity_risk": "medium",
        "heat_risk": "medium",
        "el_nino_resilience": "medium",
        "cycle": "quarterly",
        "best_planting_months": [4, 5, 6],
        "avoid_planting_months": [11, 12, 1],
    },
    "papaya": {
        "name_es": "Papaya",
        "flood_risk": "high",
        "drought_risk": "medium",
        "salinity_risk": "medium",
        "heat_risk": "low",
        "el_nino_resilience": "low",    # flooding causes rapid crown rot
        "cycle": "annual",
        "avoid_planting_months": [10, 11, 12, 1, 2],
    },
    "tuna": {
        "name_es": "Tuna (nopal)",
        "flood_risk": "very_high",  # cactus rots in standing water
        "drought_risk": "very_low", # extremely drought-tolerant
        "salinity_risk": "low",
        "heat_risk": "very_low",
        "el_nino_resilience": "low",
        "cycle": "perennial",
        "notes_es": "Útil como cortaviento y cobertura en zonas muy secas, pero sensible a inundación.",
    },
    "algodon": {
        "name_es": "Algodón",
        "flood_risk": "medium",
        "drought_risk": "medium",
        "salinity_risk": "high",    # coastal saline soils reduce yields
        "heat_risk": "low",
        "el_nino_resilience": "medium",
        "cycle": "annual",
        "best_planting_months": [10, 11],
        "avoid_planting_months": [1, 2, 3],
    },
}

# ── Dataclass for a single recommendation ────────────────────────────────────

@dataclass
class CropRecommendation:
    crop: str
    severity: Severity
    title_es: str
    body_es: str
    action_es: str


# ── Main recommendation engine ────────────────────────────────────────────────

def generate_recommendations(
    icen_state: str,
    icen_anom: float,
    month: int | None = None,
    soil_moisture_0_1cm: float | None = None,
    pct_capacity: float | None = None,
) -> list[CropRecommendation]:
    """Generate crop recommendations for the Sayariy parcel.

    Parameters
    ----------
    icen_state   : one of imarpe_icen.IcenState literals
    icen_anom    : Niño 1+2 anomaly in °C
    month        : calendar month (1-12). Defaults to current month.
    soil_moisture_0_1cm : surface soil moisture m³/m³ (from Open-Meteo forecast)
    pct_capacity : well % capacity (0-100). Used to modulate water-intensive advice.
    """
    if month is None:
        month = dt.date.today().month

    recs: list[CropRecommendation] = []

    el_nino_active  = icen_state in ("el_nino_costero", "el_nino_fuerte", "el_nino_extraordinario")
    la_nina_active  = icen_state == "la_nina_costera"
    flood_season    = month in (1, 2, 3, 4)        # Jan-Apr peak flood risk on coast
    dry_season      = month in (5, 6, 7, 8, 9)     # May-Sep dry season
    approach_season = month in (10, 11, 12)         # Oct-Dec: El Niño ramp-up

    well_low = pct_capacity is not None and pct_capacity < 40
    soil_dry = soil_moisture_0_1cm is not None and soil_moisture_0_1cm < 0.12

    # ── 1. MARACUYÁ (primary crop — 3 ha / 3,500 plants) ──────────────────
    if el_nino_active and flood_season:
        recs.append(CropRecommendation(
            crop="maracuya",
            severity="red",
            title_es="⚠️ Maracuyá: riesgo de encharcamiento activo",
            body_es=(
                f"El Niño Costero {_icen_label(icen_state)} (ICEN {icen_anom:+.2f} °C) está activo "
                f"y estamos en la temporada de mayor riesgo de lluvias (ene-abr). "
                f"La maracuyá es muy sensible al encharcamiento: las raíces se pudren "
                f"en suelo saturado en 48-72 horas (Fusarium, Phytophthora). "
                f"Datos Lambayeque 2017: pérdidas severas en cítricos y cultivos de raíz; "
                f"los frutales de exportación resistieron mejor solo cuando el drenaje era bueno."
            ),
            action_es=(
                "✅ Acción inmediata: limpie y profundice los canales de drenaje de la parcela. "
                "Considere cosechar los frutos maduros antes del pico de lluvias. "
                "No plante nuevas guías en zonas bajas hasta mayo."
            ),
        ))
    elif el_nino_active and approach_season:
        recs.append(CropRecommendation(
            crop="maracuya",
            severity="yellow",
            title_es="🌧️ Maracuyá: prepararse para temporada de lluvias El Niño",
            body_es=(
                f"El Niño Costero {_icen_label(icen_state)} (ICEN {icen_anom:+.2f} °C). "
                f"La temporada de riesgo (ene-abr) se aproxima. La maracuyá actual "
                f"debería estar en plena producción — es momento de fortalecer el drenaje "
                f"y revisar el estado de las guías antes de las lluvias."
            ),
            action_es=(
                "✅ Revise drenaje perimetral antes de diciembre. "
                "Anticipe cosecha de lotes con fruta madura. "
                "Evalúe si ampliar la maracuyá — espere a mayo para nuevas siembras."
            ),
        ))
    elif la_nina_active:
        recs.append(CropRecommendation(
            crop="maracuya",
            severity="yellow",
            title_es="🌵 Maracuyá: temporada seca prolongada — refuerce el riego",
            body_es=(
                f"La Niña Costera activa (ICEN {icen_anom:+.2f} °C): costa más fría y seca, "
                f"menor recarga al acuífero. La maracuyá necesita riego constante; "
                f"con el pozo al {pct_capacity:.0f}% de capacidad, "
                f"priorice los lotes en floración y fructificación."
                if pct_capacity else
                f"La Niña Costera activa (ICEN {icen_anom:+.2f} °C). "
                f"Monitoree el nivel del pozo — menor recarga esperada."
            ),
            action_es=(
                "✅ Mantenga riego por goteo en los turnos normales. "
                "Considere mulching (cobertura del suelo) para reducir evaporación. "
                "Monitoree el nivel del pozo semanalmente."
            ),
        ))
    elif el_nino_active and dry_season:
        recs.append(CropRecommendation(
            crop="maracuya",
            severity="yellow",
            title_es="🗓️ Maracuyá: temporada seca, pero El Niño Costero activo — prepare ya",
            body_es=(
                f"Estamos en temporada seca (bajo riesgo inmediato de inundación), pero el "
                f"El Niño Costero {_icen_label(icen_state)} (ICEN {icen_anom:+.2f} °C) sigue activo. "
                f"Históricamente los eventos costeros fuertes se intensifican en enero-marzo. "
                f"Mayo-septiembre es la ventana para preparar la infraestructura de drenaje "
                f"ANTES de que llegue la temporada de riesgo."
            ),
            action_es=(
                "✅ Limpie y amplíe canales de drenaje perimetrales ahora (trabajo en seco). "
                "Revise las canaletas de las guías de maracuyá. "
                "Programe el mantenimiento antes de octubre. "
                "La cosecha del ciclo actual es su mejor seguro — no deje fruta madura en la planta."
            ),
        ))
    else:
        recs.append(CropRecommendation(
            crop="maracuya",
            severity="green",
            title_es="✅ Maracuyá: condiciones normales",
            body_es=(
                f"ENSO neutro (ICEN {icen_anom:+.2f} °C). "
                f"{'Temporada seca — riego normal.' if dry_season else 'Temporada de transición.'} "
                f"La maracuyá está en su ventana óptima de producción."
            ),
            action_es="Continúe el calendario de riego habitual. No se requieren acciones especiales.",
        ))

    # ── 2. PALTA / AVOCADO (más sensible al encharcamiento del huerto) ──────
    if el_nino_active and (flood_season or approach_season):
        recs.append(CropRecommendation(
            crop="huertos_palta",
            severity="red" if flood_season else "yellow",
            title_es="⚠️ Palta: NO expandir en zonas bajas — El Niño activo",
            body_es=(
                f"La palta es el cultivo más sensible al encharcamiento de todos los huertos "
                f"(incluso 24h de suelo saturado causa muerte radicular). "
                f"French et al. (2023) documenta que en 2017 la palta nacional resistió "
                f"(+2.5%), pero solo en parcelas con buen drenaje. "
                f"En suelos aluviales de Cayaltí con El Niño {_icen_label(icen_state)}, "
                f"las zonas bajas de los huertos son de alto riesgo."
            ),
            action_es=(
                "🚫 No plante nuevos árboles de palta en zonas bajas este ciclo. "
                "✅ Asegure drenaje en los huertos existentes. "
                "Si tiene lotes en pendiente positiva, priorice la palta allí."
            ),
        ))

    # ── 3. ROTACIÓN FRIJOL / MAÍZ ────────────────────────────────────────────
    if dry_season and not la_nina_active:
        recs.append(CropRecommendation(
            crop="frijol",
            severity="green",
            title_es="🌿 Rotación frijol/maíz: momento ideal",
            body_es=(
                f"Mayo-septiembre es la ventana óptima para la rotación trimestral. "
                f"ENSO {'neutro' if icen_state == 'neutral' else _icen_label(icen_state)} "
                f"(ICEN {icen_anom:+.2f} °C): sin riesgo de inundación. "
                f"El frijol fija nitrógeno y mejora la estructura del suelo aluvial de Cayaltí "
                f"— importante dado el riesgo de salinización documentado en la zona Cayaltí-Zaña "
                f"(INIA, Concytec 2024)."
            ),
            action_es=(
                "✅ Plante frijol o maíz ahora para cosechar antes de octubre. "
                "Prefiera frijol sobre maíz si el nivel del pozo está bajo "
                "(Kc frijol 1.15 vs maíz 1.20 — demanda similar, pero el frijol aporta N al suelo)."
                if not well_low else
                "✅ Con el pozo bajo, prefiera frijol sobre maíz (menor demanda hídrica total). "
                "Coseche antes de octubre para liberar el suelo antes de la temporada húmeda."
            ),
        ))
    elif approach_season and el_nino_active:
        recs.append(CropRecommendation(
            crop="frijol",
            severity="yellow",
            title_es="⏰ Rotación: plante ya o espere hasta mayo",
            body_es=(
                f"Con El Niño Costero {_icen_label(icen_state)} activo, los meses oct-dic son "
                f"de riesgo creciente. Si planta ahora, asegúrese de que la cosecha sea antes "
                f"de enero. Si no llega a tiempo, es mejor esperar a mayo (temporada seca)."
            ),
            action_es=(
                "⚠️ Solo plante si puede cosechar antes del 15 de enero. "
                "De lo contrario, espere a mayo para la siguiente rotación."
            ),
        ))

    # ── 4. CULTIVOS A CONSIDERAR según condiciones actuales ──────────────────
    if el_nino_active and dry_season:
        recs.append(CropRecommendation(
            crop="_suggestion",
            severity="green",
            title_es="💡 Cultivos resilientes para diversificar",
            body_es=(
                f"Con El Niño Costero {_icen_label(icen_state)} activo, los siguientes cultivos "
                f"son opciones de bajo riesgo para el área de rotación "
                f"(basado en French et al. 2023, resistencia en 2017): "
                f"• Espárrago: Lambayeque tiene 21% del área nacional; altamente resiliente "
                f"a El Niño Costero (datos históricos); demanda hídrica manejable con drip. "
                f"• Algodón: tradicional de la costa norte, tolera el calor, ciclo oct-mar "
                f"(siembra antes del pico de lluvias). "
                f"• Camote: corto ciclo (90-120 días), tolera stress hídrico moderado."
            ),
            action_es=(
                "💡 Para expandir producción resiliente al ENSO, consulte con INIA Vista "
                "Florida (Picsi, Chiclayo) — tienen variedades adaptadas al clima de Lambayeque."
            ),
        ))

    if la_nina_active:
        recs.append(CropRecommendation(
            crop="_suggestion",
            severity="yellow",
            title_es="🌵 La Niña: priorice cultivos de bajo consumo hídrico",
            body_es=(
                f"La Niña Costera (ICEN {icen_anom:+.2f} °C): temporada seca más prolongada, "
                f"menor recarga del acuífero. Priorice cultivos eficientes en agua: "
                f"• Tuna/nopal: muy bajo Kc (0.35), excelente para zonas con restricción hídrica. "
                f"• Frijol en lugar de maíz (Kc similar pero fija nitrógeno). "
                f"• Reduzca el área de maracuyá si el pozo baja de 2.5 m."
            ),
            action_es=(
                "⚠️ Monitoree el nivel del pozo quincenalmente. "
                "Si baja de 2.5 m, suspenda nuevas siembras y concentre el agua en "
                "maracuyá productiva y árboles establecidos."
            ),
        ))

    # ── 5. SOIL SALINITY WARNING (Cayaltí-Zaña documented risk) ──────────────
    if soil_dry and well_low:
        recs.append(CropRecommendation(
            crop="_salinity",
            severity="yellow",
            title_es="⚗️ Riesgo de salinización del suelo — monitorear",
            body_es=(
                f"Suelo superficial seco (humedad {soil_moisture_0_1cm:.2f} m³/m³) y pozo bajo. "
                f"Los suelos aluviales de la zona Cayaltí-Zaña tienen riesgo documentado "
                f"de salinización (INIA/Concytec). Con extracción intensiva de agua subterránea, "
                f"pueden ascender sales de capas profundas. El algodón y la palta son los cultivos "
                f"más sensibles a la salinidad en su parcela."
            ),
            action_es=(
                "✅ Si dispone de un conductímetro, mida la CE del agua de riego. "
                "Valores >1.5 dS/m afectan maracuyá; >2.0 dS/m dañan palta. "
                "Añada el dato al formulario de medición del dashboard para seguimiento."
            ),
        ))

    return recs


def _icen_label(state: str) -> str:
    return {
        "el_nino_extraordinario": "Extraordinario",
        "el_nino_fuerte":         "Fuerte",
        "el_nino_costero":        "Moderado",
        "neutral":                "Neutro",
        "la_nina_costera":        "La Niña Costera",
    }.get(state, state)


def severity_color(severity: Severity) -> str:
    return {"green": "#27AE60", "yellow": "#E67E22", "red": "#E74C3C"}.get(severity, "#566D7E")


def severity_bg(severity: Severity) -> str:
    return {"green": "#EAFAF1", "yellow": "#FEF9E7", "red": "#FDEDEC"}.get(severity, "#F8F9FA")


if __name__ == "__main__":
    recs = generate_recommendations(
        icen_state="el_nino_fuerte",
        icen_anom=1.52,
        month=5,
        soil_moisture_0_1cm=0.09,
        pct_capacity=33.0,
    )
    for r in recs:
        print(f"[{r.severity.upper()}] {r.title_es}")
        print(f"  {r.body_es[:120]}...")
        print(f"  → {r.action_es[:100]}...")
        print()
