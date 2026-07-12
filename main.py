from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import PlainTextResponse
import requests
from dotenv import load_dotenv
import os

# استيراد دالة معالجة الريكورد من ملف التست المساعد
from test import process_whatsapp_audio

app = FastAPI()
load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# 🗂️ قاموس لحفظ حالة كل مستخدم وبيانات حجزوه مؤقتاً في الذاكرة
user_sessions = {}

# ---------------- FUNCTION TO SEND TEXT ----------------
def send_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=data)

# ---------------- FUNCTION TO SEND BUTTONS (Max 3) ----------------
def send_buttons(to, text, buttons_titles):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    
    buttons = []
    for i, title in enumerate(buttons_titles):
        buttons.append({
            "type": "reply",
            "reply": {"id": f"btn_{i}", "title": title}
        })
        
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {"buttons": buttons}
        }
    }
    requests.post(url, headers=headers, json=data)

# ---------------- FUNCTION TO SEND LIST / DROPDOWN ----------------
def send_list(to, body_text, button_label, row_titles):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    
    rows = []
    for i, title in enumerate(row_titles):
        rows.append({"id": f"row_{i}", "title": title})
        
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_label,
                "sections": [{"title": "التخصصات المتاحة", "rows": rows}]
            }
        }
    }
    requests.post(url, headers=headers, json=data)

# ---------------- FUNCTION TO SEND DOCTORS CARDS (3 DOCTORS PER SPECIALTY) ----------------
def send_doctors_cards(to, specialty):
    """إرسال كروت الأطباء المتاحين (3 أطباء لكل تخصص) بناءً على التخصص الذي اختاره المستخدم"""
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    
    # روابط صور افتراضية للأطباء من Unsplash
    img_female1 = "https://static.vecteezy.com/system/resources/previews/005/130/413/large_2x/smart-woman-doctor-is-holding-stethoscope-free-photo.jpg"
    img_male1 = "https://static.vecteezy.com/system/resources/previews/026/375/416/large_2x/ai-generative-portrait-of-confident-male-doctor-in-white-coat-and-stethoscope-standing-with-arms-crossed-and-looking-at-camera-photo.jpg"
    img_male2 = "https://static.vecteezy.com/system/resources/previews/004/623/301/large_2x/successful-senior-doctor-in-hospital-cabinet-photo.jpg"

    # تصنيف 3 أطباء لكل تخصص متاح
    specialties_data = {
        "طبيب اورام 🩺": [
            {"name": "د. أحمد سمير", "info": "👨‍⚕️ د. أحمد سمير\n✨ استشاري أورام - خبرة 10 سنوات", "img": img_male1},
            {"name": "د. رانيا ممدوح", "info": "👩‍⚕️ د. رانيا ممدوح\n✨ أخصائي علاج الأورام - خبرة 5 سنوات", "img": img_female1},
            {"name": "د. كريم شريف", "info": "👨‍⚕️ د. كريم شريف\n✨ مدرس وعضو هيئة التدريس - خبرة 4 سنوات", "img": img_male2}
        ],
        "طبيب عام 👨‍⚕️": [
            {"name": "د. ياسمين علي", "info": "👩‍⚕️ د. ياسمين علي\n✨ طبيب عام بمستشفى الجامعة - خبرة 5 سنوات", "img": img_female1},
            {"name": "د. مصطفى محمود", "info": "👨‍⚕️ د. مصطفى محمود\n✨ ممارس عام باطني - خبرة 6 سنوات", "img": img_male1},
            {"name": "د. خالد نور", "info": "👨‍⚕️ د. خالد نور\n✨ طبيب مقيم باطنة وعام - خبرة 3 سنوات", "img": img_male2}
        ],
        "طبيب قلب ❤️": [
            {"name": "د. محمد خالد", "info": "👨‍⚕️ د. محمد خالد\n✨ أخصائي أمراض القلب والأوعية - خبرة 7 سنوات", "img": img_male2},
            {"name": "د. منى زكي", "info": "👩‍⚕️ د. منى زكي\n✨ استشاري أمراض وقسطرة القلب - خبرة 9 سنوات", "img": img_female1},
            {"name": "د. هشام عادل", "info": "👨‍⚕️ د. هشام عادل\n✨ أخصائي قلب وأوعية دموية - خبرة 4 سنوات", "img": img_male1}
        ],
        "طبيب أعصاب 🧠": [
            {"name": "د. طارق عمر", "info": "👨‍⚕️ د. طارق عمر\n✨ استشاري جراحة المخ والأعصاب - خبرة 8 سنوات", "img": img_male1},
            {"name": "د. نهى السعيد", "info": "👩‍⚕️ د. نهى السعيد\n✨ أخصائي أمراض المخ والأعصاب - خبرة 5 سنوات", "img": img_female1},
            {"name": "د. وائل رأفت", "info": "👨‍⚕️ د. وائل رأفت\n✨ طبيب أمراض عصبية ونفسية - خبرة 4 سنوات", "img": img_male2}
        ],
        "طبيب أطفال 👶": [
            {"name": "د. سارة محمود", "info": "👩‍⚕️ د. سارة محمود\n✨ أخصائي طب الأطفال وحديثي الولادة - خبرة 6 سنوات", "img": img_female1},
            {"name": "د. حازم توفيق", "info": "👨‍⚕️ د. حازم توفيق\n✨ استشاري طب الأطفال والمبتسرين - خبرة 11 سنة", "img": img_male1},
            {"name": "د. عمرو دياب", "info": "👨‍⚕️ د. عمرو دياب\n✨ أخصائي أطفال رعاية مركزة - خبرة 3 سنوات", "img": img_male2}
        ]
    }

    # جلب قائمة الأطباء التابعين للتخصص المختار
    selected_doctors = specialties_data.get(specialty, [])

    if not selected_doctors:
        print(f"⚠️ تنبيه: لم يتم العثور على أطباء مسجلين للتخصص: {specialty}")
        send_message(to, f"عذراً، لا يوجد أطباء متاحين حالياً في تخصص {specialty}.")
        return

    print(f"⏳ جاري إرسال كروت أطباء تخصص ({specialty}) إلى {to}...")
    send_message(to, f"🏥 الأطباء المتاحين حالياً في تخصص ({specialty}):")

    # إرسال كروت الـ 3 أطباء متتالية بشكل عمودي منظم
    for doc in selected_doctors:
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "image",
                    "image": {"link": doc["img"]}
                },
                "body": {
                    "text": doc["info"]
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"select_{doc['name']}",
                                "title": f"اختيار {doc['name']}"
                            }
                        }
                    ]
                }
            }
        }
        response = requests.post(url, headers=headers, json=data)
        print(f"📦 إرسال كارت دكتور ({doc['name']}): {response.status_code}")

# ---------------- VERIFY WEBHOOK ----------------
@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)
    return PlainTextResponse(content="verification failed")

# ---------------- WEBHOOK (RECEIVE & PROCESS) ----------------
@app.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()
    
    try:
        value = data["entry"][0]["changes"][0]["value"]
        
        if "messages" not in value:
            return {"status": "status_update_ignored"}
            
        message = value["messages"][0]
        user_number = message["from"]
        
        user_text = ""
        
        # 1. فحص نوع الرسالة: لو العميل بعت ريكورد صوتي
        if message.get("type") == "audio":
            media_id = message["audio"]["id"]
            print(f"🎙️ استقبلت ريكورد صَوتي بـ ID: {media_id} من {user_number}. جاري التفريغ برمجياً...")
            user_text = process_whatsapp_audio(media_id)
            print(f" [نتيجة تفريغ الريكورد]: {user_text}")

        # 2. لو الرسالة نصية عادية مكتوبة
        elif "text" in message:
            user_text = message["text"]["body"].strip()
            
        # 3. لو ضغط على زرار أو قائمة تفاعلية
        elif "interactive" in message:
            if message["interactive"]["type"] == "button_reply":
                user_text = message["interactive"]["button_reply"]["title"]
            elif message["interactive"]["type"] == "list_reply":
                user_text = message["interactive"]["list_reply"]["title"]

        # إذا لم ننجح في الحصول على نص (وليس أوديو)، نتوقف هنا
        if not user_text and message.get("type") != "audio":
            print("⚠️ لم يتم استخراج أي نص من الرسالة الحالية.")
            return {"status": "no_text_extracted"}

        # تهيئة الجلسة للمقبلين الجدد (أول رسالة أياً كانت تبدأ الترحيب)
        if user_number not in user_sessions:
            user_sessions[user_number] = {"step": "WELCOME", "booking_info": {}}

        current_step = user_sessions[user_number]["step"]
        print(f"📱 الخطوة الحالية: {current_step} | للمستخدم: {user_number} | 💬 النص: {user_text}")

        # شجرة الردود والتحكم بالخطوات (شات بوت المستشفى)
        if current_step == "WELCOME":
            user_sessions[user_number]["step"] = "MAIN_MENU"
            send_message(user_number, "مستشفى جامعة نيو جيزة ترحب بكم 🏥")
            send_buttons(
                to=user_number, 
                text="أنا هنا لمساعدتك في العثور على الطبيب المناسب وحجز موعد. لنبدأ 👇", 
                buttons_titles=["البحث عن طبيب", "حجز موعد"]
            )
            
        elif current_step == "MAIN_MENU" and (user_text == "البحث عن طبيب" or user_text == "حجز موعد"):
            user_sessions[user_number]["step"] = "CHOOSE_SPECIALTY"
            send_list(
                to=user_number,
                body_text="ما هو التخصص الطبي الذي تبحث عنه؟",
                button_label="Choose...",
                row_titles=["طبيب اورام 🩺", "طبيب عام 👨‍⚕️", "طبيب قلب ❤️", "طبيب أعصاب 🧠", "طبيب أطفال 👶"]
            )

        elif current_step == "CHOOSE_SPECIALTY":
            user_sessions[user_number]["booking_info"]["specialty"] = user_text
            user_sessions[user_number]["step"] = "CHOOSE_DOCTOR"
            
            # استدعاء الدالة المحدثة لفلترة وعرض 3 أطباء للتخصص المختار
            send_doctors_cards(to=user_number, specialty=user_text)

        elif current_step == "CHOOSE_DOCTOR":
            # تنظيف النص المرجّع من الزر الجديد لحفظ اسم الدكتور المختار فقط (حذف كلمة اختيار)
            doctor_name = user_text.replace("اختيار ", "").strip()
            
            user_sessions[user_number]["booking_info"]["doctor"] = doctor_name
            user_sessions[user_number]["step"] = "CHOOSE_TYPE"
            send_buttons(
                to=user_number,
                text=f"تم اختيار {doctor_name} ✅\n\nاختر نوع الكشف:",
                buttons_titles=["كشف جديد", "اعاده كشف"]
            )

        elif current_step == "CHOOSE_TYPE":
            user_sessions[user_number]["booking_info"]["type"] = user_text
            user_sessions[user_number]["step"] = "GET_NAME"
            send_message(user_number, "برجاء ادخال المعلومات الاتيه :\n\n✍️ اسم المريض :")

        elif current_step == "GET_NAME":
            user_sessions[user_number]["booking_info"]["name"] = user_text
            user_sessions[user_number]["step"] = "GET_AGE"
            send_message(user_number, "⏳ سن المريض :")

        elif current_step == "GET_AGE":
            user_sessions[user_number]["booking_info"]["age"] = user_text
            info = user_sessions[user_number]["booking_info"]
            
            summary = (
                f"📝 ملخص بيانات الحجز:\n"
                f"- اسم المريض: {info.get('name')}\n"
                f"- السن: {info.get('age')} سنة\n"
                f"- التخصص: {info.get('specialty')}\n"
                f"- الدكتور: {info.get('doctor')}\n"
                f"- نوع الكشف: {info.get('type')}\n\n"
                f"شكرا لقد تم تأكيد المعاد بطلبك! 🎉"
            )
            send_message(user_number, summary)
            del user_sessions[user_number]

    except Exception as e:
        print("❌ Error caught:", e)

    return {"status": "ok"}

# ---------------- LOCAL ASR SERVER ENDPOINT ----------------
@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        transcription_text = "النص المستخرج من الريكورد" 
        return {"transcription": transcription_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # img_dr1 = "https://static.vecteezy.com/system/resources/previews/005/130/413/large_2x/smart-woman-doctor-is-holding-stethoscope-free-photo.jpg"
    # img_dr2 = "https://static.vecteezy.com/system/resources/previews/026/375/416/large_2x/ai-generative-portrait-of-confident-male-doctor-in-white-coat-and-stethoscope-standing-with-arms-crossed-and-looking-at-camera-photo.jpg"
    # img_dr3 = "https://static.vecteezy.com/system/resources/previews/004/623/301/large_2x/successful-senior-doctor-in-hospital-cabinet-photo.jpg"
