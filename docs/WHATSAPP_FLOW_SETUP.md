# WhatsApp Flows — Doctor ImageCarousel trial

Goal: swipe doctor photos left/right inside WhatsApp (no marketing carousel template),
then pick a doctor from a radio list. Same booking logic continues after selection.

## 1) Install dependency

```bash
pip install Pillow
```

## 2) Create the Flow in Meta

1. Open [Meta WhatsApp Manager](https://business.facebook.com/) → your WhatsApp account  
2. **Account tools** → **Flows** → **Create Flow**  
3. Choose a blank / custom flow (not a marketing carousel template)  
4. Open the JSON editor and paste contents of:

`app/flows/doctor_picker.json`

5. Save → **Publish** the Flow (or keep Draft for testing with `"mode": "draft"`)  
6. Copy the **Flow ID**

## 3) Enable in `.env`

```env
USE_DOCTOR_FLOW=true
WHATSAPP_FLOW_ID=your_flow_id_here
WHATSAPP_FLOW_CTA=عرض الأطباء
```

Leave `USE_DOCTOR_FLOW=false` to keep sequential doctor cards (current fallback).

## 4) Restart API + tunnel

```bash
uvicorn app.main:app --reload
.\cloudflared tunnel --url http://localhost:8000
```

## 5) Try on WhatsApp

1. Message the bot → **حجز موعد**  
2. Choose **بالتخصص** or **كل الأطباء**  
3. You should get a Flow button → open it  
4. Swipe images → select doctor from the list → **متابعة**  
5. Booking continues (date → slot → name → confirm)

## Notes

- ImageCarousel shows up to **3** photos (Meta limit). Radio list can show more doctors.  
- Images are resized/compressed from `doctors.photo_url` in the DB.  
- If Flow send fails, the bot automatically falls back to sequential cards.  
- To disable anytime: set `USE_DOCTOR_FLOW=false` and restart.
