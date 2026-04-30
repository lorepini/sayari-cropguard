# CropGuard / AquaSafe — Backlog (post-May 14, 2026)

Items deferred from the May 14 final presentation. Use this as the source for the
"Future Work" / "Próximos pasos" slide and any post-symposium roadmap.

---

## 1. WhatsApp alerts (push)

**Why:** NGO field workers don't sit at a dashboard. They live in WhatsApp.
A push channel is the only way alerts will actually reach the right person on
the day they matter.

**What:**
- Trigger when `days_until_critical(threshold_m=2.0) ≤ 7` for Pozo 1, or when
  the next-3-day rain forecast jumps above a "flood-risk" band during El Niño.
- Plain-Spanish message, emoji-led, one screenful max:
  > 🔴 *Aviso CropGuard* — el pozo está bajando rápido. En ~5 días podría
  > faltar agua. Reduzca el riego hoy. Más detalle: cropguard-0k17.onrender.com

**How (rough sketch):**
- Twilio WhatsApp Business API or Meta Cloud API.
- Daily cron (e.g. GitHub Actions schedule) hits the model, evaluates rules,
  POSTs to the API only on state change (no daily-noise spam).
- NGO maintains a recipient list in a small JSON config — easy to edit.
- Cost reality check: Meta charges per "service conversation" — at <50 alerts
  per month this is essentially free, but read the pricing tier before scaling.

**Effort:** ~2–3 days for a working pilot to one phone number. Real rollout
needs the NGO to register a WhatsApp Business profile.

---

## 2. Weekly / monthly email reports

**Why:** NGO leadership (decision-makers, not field workers) want a periodic
written summary they can forward to donors and partners. WhatsApp pushes the
operational alert; email carries the narrative + accountability artefacts.

**What:**
- **Weekly digest:** ~1 page — current pozo state, rainfall last week, ENSO
  state, irrigation recommendations for next week, any active alerts.
- **Monthly report:** ~3 pages — same plus a 4-week historical chart, calibrated
  forecast for next month, summary of crop-stress alerts (NDVI tab), comparison
  vs. same month last year.
- Format: HTML email with embedded PNG charts, plus PDF attachment for archival.

**How:**
- Generate PDF via `reportlab` or render HTML+CSS through `weasyprint`.
- Send via SMTP (SendGrid free tier handles low volume) or transactional email API.
- Schedule with the same cron that drives WhatsApp alerts.
- Spanish-language, plain prose — same audience principle as Vista Sencilla.

**Effort:** ~4–5 days for a polished first version. Most of the work is
designing the layout/copy, not the plumbing.

---

## 3. Other items worth flagging in the "Future Work" slide

- **Pozo 2 reactivation modelling.** When the NGO repairs Pozo 2, the model
  pump cap restores from 52,500 → 95,500 L/day. The data structures already
  support both wells; only the `status` field in `wells.geojson` plus
  `PUMP_CAPACITY_L_PER_DAY` need to flip.
- **Sentinel-1 SAR soil moisture.** Acknowledged in `alignment_response.md` as
  a future-work item; would close the gap with the HydroGuard reference paper.
- **Verified Maracuyá / multi-crop Kc.** Replace the "verify" placeholders in
  `src/water_balance.CROP_KC_DEFAULT` with FAO-56 / agronomy-paper values that
  the team confirms. Re-run `scripts/calibrate_water_balance.py` afterwards.
- **NGO crop mix confirmation.** The current `DEFAULT_CROP_MIX` is hypothetical
  (3,500 maracuyá + 5 naranja + 6 maíz + 5 cebolla + 4 cilantro). Replace once
  the NGO confirms per-chacra crop assignments.
- **Per-chacra granularity.** Today the model treats the whole parcel as one
  demand sink. Splitting demand per chacra would let the dashboard surface
  "chacra X is stressed" rather than just "the parcel is stressed" — but this
  needs per-chacra geometry from the NGO.

---

_Last updated: 2026-04-30. Owner: project group, ESADE PAIBS Spring 2026._
