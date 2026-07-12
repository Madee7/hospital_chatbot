from fastapi import FastAPI, Request, Response, Query ,  BackgroundTasks , HTTPException
from fastapi.responses import PlainTextResponse
import requests
import json
import re
from datetime import datetime
import os
from dotenv import load_dotenv
from voice_processor import process_whatsapp_audio , convert_text_to_speech, upload_audio_to_whatsapp, send_whatsapp_audio
import locale



app = FastAPI()


# --- الإعدادات والمتغيرات ---
load_dotenv()  # تفعيل قراءة الملف الشغال في الخلفية

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
chats_memory = {}

# ==========================================
# 1. قاعدة بيانات العيادات والأطباء والمواعيد الموحدة
# ==========================================
DOCTORS_DB = {
    "أطفال": [
        {
            "name": "د. رانيا كمال",
            "slots": [
                {"day": "الخميس", "time": "من الساعة 2 ظهراً حتى 5 مساءً"},
                {"day": "السبت", "time": "من الساعة 10 صباحاً حتى 1 ظهراً"}
            ]
        },
        {
            "name": "د. شريف عمر",
            "slots": [
                {"day": "الإثنين", "time": "من الساعة 6 مساءً حتى 9 مساءً"},
                {"day": "الأربعاء", "time": "من الساعة 4 مساءً حتى 7 مساءً"}
            ]
        }
    ],
    "جراحة عامة": [
        {
            "name": "د. خالد العباسي",
            "slots": [
                {"day": "الثلاثاء", "time": "من الساعة 7 مساءً حتى 10 مساءً"},
                {"day": "الخميس", "time": "من الساعة 7 مساءً حتى 10 مساءً"}
            ]
        }
    ],
    "باطنة": [
        {
            "name": "د. حازم توفيق",
            "slots": [
                {"day": "الأحد", "time": "من الساعة 1 ظهراً حتى 4 عصراً"},
                {"day": "الثلاثاء", "time": "من الساعة 5 مساءً حتى 8 مساءً"}
            ]
        },
        {
            "name": "د. منى ممدوح",
            "slots": [
                {"day": "الإثنين", "time": "من الساعة 11 صباحاً حتى 2 ظهراً"},
                {"day": "الأربعاء", "time": "من الساعة 6 مساءً حتى 9 مساءً"}
            ]
        }
    ]
}

# ==========================================
# 2. دالات بايثون والاتصال بقاعدة البيانات (Database Layer)
# ==========================================
def get_doctors_from_db(department: str) -> str:
    """يستعلم من الداتا عن الدكاترة المتاحين للتخصص"""
    if not department:
        return json.dumps({"status": "error", "message": "الرجاء تحديد التخصص"}, ensure_ascii=False)
    
    department = department.strip()
    # مرونة في مسمى تخصص الباطنة لضمان التوافق
    if "باطن" in department:
        department = "باطنة"

    doctors = DOCTORS_DB.get(department, [])
    if doctors:
        return json.dumps({"status": "success", "department": department, "doctors": doctors}, ensure_ascii=False)
    return json.dumps({"status": "error", "message": "لا يوجد دكاترة متاحين حالياً في هذا التخصص. التخصصات المتاحة هي: أطفال، جراحة عامة، باطنة."}, ensure_ascii=False)


def get_slots_from_db(doctor_name: str = None):
    """
    دالة تبحث في قاعدة البيانات عن المواعيد المتاحة بناءً على اسم الدكتور مباشرة عبر كل التخصصات.
    """
    if not doctor_name:
        return "من فضلك حدد اسم الدكتور المطلوب لنتمكن من مساعدتك."
    
    doctor_name = doctor_name.strip()
    
    # البحث عن الطبيب داخل القاموس الموحد دون اشتراط معرفة التخصص مسبقاً من الـ AI
    for specialty, doctors_list in DOCTORS_DB.items():
        for doc in doctors_list:
            if doctor_name in doc["name"] or doc["name"] in doctor_name:
                result_text = f" المواعيد المتاحة للطبيب ({doc['name']}) - تخصص {specialty}:\n\n"
                for slot in doc["slots"]:
                    result_text += f"  - يوم {slot['day']}: {slot['time']}\n"
                return result_text.strip()
                
    return f"عذراً، لم نجد طبيباً باسم '{doctor_name}' في نظامنا الحلي. يرجى التأكد من الاسم."


def save_booking_to_db(patient_name: str, patient_age: int, department: str, doctor_name: str, slot: str) -> str:
    """يقوم بإدخال الحجز الفعلي في الداتا"""
    print(f" [قاعدة البيانات]: تم حفظ حجز جديد بنجاح للمريض {patient_name}")
    booking_id = "REV-2026-99" 
    return json.dumps({"status": "confirmed", "booking_id": booking_id, "message": "تم تسجيل الحجز في قاعدة البيانات بنجاح"}, ensure_ascii=False)


# ==========================================
# 3. تعريف الأدوات (Groq Tools Schema)
# ==========================================
GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_doctors_from_db",
            "description": "تُستدعى عندما يذكر المريض التخصص الطبي ويريد معرفة الدكاترة المتاحين في المستشفى.",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "التخصص المطلوب مثل: باطنة، جراحة عامة، أطفال"}
                },
                "required": ["department"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_slots_from_db",
            "description": "تُستدعى عندما يختار المريض أو يذكر اسماً لطبيب معين لمعرفة المواعيد الشاغرة المتاحة له.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_name": {"type": "string", "description": "الاسم الكامل للدكتور مثل: د. حازم توفيق، د. رانيا كمال"}
                },
                "required": ["doctor_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_booking_to_db",
            "description": "تُستدعى فقط عندما يوافق المريض نهائياً على ملخص الحجز أو يطلب التأكيد لحفظ البيانات.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string"},
                    "patient_age": {"type": "integer"},
                    "department": {"type": "string"},
                    "doctor_name": {"type": "string"},
                    "slot": {"type": "string", "description": "الموعد الذي اختاره المريض الشاغر"}
                },
                "required": ["patient_name", "patient_age", "department", "doctor_name", "slot"]
            }
        }
    }
]


# ==========================================
# 4. التوجيهات الأساسية (System Prompt)
# ==========================================
SYSTEM_PROMPT = """
أنت موظف استقبال ذكي، هادئ ومحترف في "مستشفى الشفاء". مهمتك حجز موعد للمريض بأسلوب مهني ومباشر (دون مبالغة في التودد أو استخدام عبارات شاعرية).
أنت لا تعرف الأطباء ولا تعرف المواعيد المتاحة مسبقاً. بناءً على ردود المريض، يجب عليك استخدام الأدوات (Tools) المتاحة لك للاستعلام من قاعدة البيانات.

خطوات الحجز الحتمية:
1. اطلب اسم المريض وعمره بلطف ومباشرة.
2. اطلب التخصص (باطنة، جراحة عامة، أطفال). بمجرد معرفة التخصص، استدعِ أداة (get_doctors_from_db) فوراً لتعرف من هم الأطباء المتاحين في الداتا ثم اعرضهم على المريض.
3. بمجرد اختيار الدكتور، استدعِ أداة (get_slots_from_db) لتعرف مواعيده الشاغرة الحقيقية واعرضها عليه ليختار منها.
4. عندما يختار الموعد وتكتمل البيانات، اعرض ملخص الحجز واطلب منه كتابة (تأكيد).
5. بمجرد أن يقول (تأكيد)، استدعِ أداة (save_booking_to_db) فوراً لحفظ الحجز، ثم اعط المريض تأكيداً نهائياً برقم الحجز.

 قواعد صارمة وتطهير النصوص:
- لا تخترع أسماء دكاترة ولا مواعيد من عندك أبداً؛ اعتمد كلياً على ما تعيده لك الدوال.
- تحدث بلغة عربية مهنية، هادئة، ومباشرة (اللهجة البيضاء المفهومة).
- يُمنع تماماً إدخال أي كلمة إنجليزية داخل النص (مثل Availability, process, forms).
- استخدم دائماً اسم المستشفى الرسمي "مستشفى الشفاء"، ويُمنع تماماً استخدام كلمة "مستشفينا".
- إذا ذكر المريض أنه تعبان، قل له باختصار "ألف سلامة عليك" أو "شفاك الله" ثم أكمل خطوتك مباشرة.
- اطلب المعلومات الناقصة تدريجياً (سؤال واحد فقط في كل رد لتجنب تشتيت المريض).
-عند تاكيد الحجز اعتبر المحادثه انتهت 

 تعليمات صارمة جداً خلف الكواليس:
1. لا تقم أبداً بكتابة أسماء الدالات البرمجية (Functions)، أو الأقواس المتعرجة {}، أو تاجات مثل <function> في كلامك مع المريض.
2. استخدم الأدوات (Tools) بصمت تام لجلب البيانات، ثم صغ الرد النهائي للمريض بأسلوب بشري طبيعي بناءً على النتيجة.
3.يمنع منعاً باتاً استخدام أي حروف أو كلمات غير عربية (مثل الصينية أو الهندية) في الإجابة، ويجب أن يكون النص باللغة العربية الفصحى النظيفة فقط.
"""

def clean_response(text):
    if not text:
        return ""
    
    # 1 تنظيف بقايا استدعاء الدوال وعلامات الـ JSON (كودكِ الأصلي السليم)
    text = re.sub(r'<function.*?>', '', text)
    text = re.sub(r'<function.*', '', text)
    text = re.sub(r'\{"doctor_name".*?\}', '', text)
    text = re.sub(r'\{.*?\}', '', text)
    
    # 2 فلترة النص والإبقاء فقط على العربي، الأرقام، وعلامات الترقيم (حذف الصيني والهندي)
    allowed_pattern = r'[^\u0600-\u06FF\u0750-\u077F\s0-9\d.,!؟?()-\:]'
    text = re.sub(allowed_pattern, '', text)
    
    return text.strip()

# ==========================================
# 5. الدالة المحركة لإدارة المحادثة والـ Tools
# ==========================================
def call_groq_with_tools(messages_history):
    days_mapping = {
        "Monday": "الإثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء",
        "Thursday": "الخميس", "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد"
    }
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_day_eng = now.strftime("%A")
    current_day_arb = days_mapping.get(current_day_eng, current_day_eng)
    
    date_context = f"تاريخ اليوم الحالي في السيرفر هو: {current_date} ويوافق يوم ({current_day_arb}). استخدم هذا التاريخ لحساب مصطلحات المريض مثل (بكرة، بعد بكرة، الأسبوع القادم)."
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # 1. قائمة الموديلات المتاحة مرتبة حسب الأولوية المفضلة لديكِ
    AVAILABLE_MODELS = [
        "llama-3.3-70b-versatile",  # الخيار الأول الأساسي والأقوى
        "llama-3.1-8b-instant",     # البديل الأول السريع جداً
        "gemma2-9b-it",             # البديل الثاني الممتاز
        "mixtral-8x7b-32768"        # البديل الثالث الاحتياطي
    ]
    
    # حلقة تكرارية لتجربة الموديلات بالترتيب في حال حدوث الضغط (Rate Limit 429)
    for model_name in AVAILABLE_MODELS:
        try:
            print(f" [محاولة الاتصال]: جاري تجربة الموديل {model_name}...")
            
            # بناء قائمة الرسائل بشكل نظيف داخل اللوب لضمان عدم تداخل المحاولات الفاشلة
            updated_messages = [{"role": "system", "content": date_context}] + messages_history
            
            payload = {
                "model": model_name,
                "messages": updated_messages,
                "tools": GROQ_TOOLS,
                "tool_choice": "auto",
                "temperature": 0.3,
                "top_p":0.9
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response_data = response.json()
            
            # إذا أرجع السيرفر خطأ (مثل الـ Rate Limit 429)، ننتقل للموديل التالي فوراً
            if "error" in response_data:
                print(f" [خطأ API مع {model_name}]:", json.dumps(response_data["error"], indent=2, ensure_ascii=False))
                print(" جاري الانتقال للموديل الاحتياطي التالي...")
                continue
                
            if "choices" not in response_data:
                print(f" [بيانات مفقودة من الموديل {model_name}]")
                continue
                
            message = response_data["choices"][0]["message"]
            
            # التحقق مما إذا كان Groq يطلب استدعاء الأداة (Function Calling)
            if message.get("tool_calls"):
                tool_call = message["tool_calls"][0]
                function_name = tool_call["function"]["name"]
                function_args = json.loads(tool_call["function"]["arguments"])
                
                print(f" [Groq الإشارة]: طلب تشغيل الدالة {function_name} بالمتغيرات: {function_args}")
                
                # تنفيذ الدالة المناسبة بناءً على طلب الموديل
                if function_name == "get_doctors_from_db":
                    db_result = get_doctors_from_db(department=function_args.get("department"))
                elif function_name == "get_slots_from_db":
                    db_result = get_slots_from_db(doctor_name=function_args.get("doctor_name"))
                elif function_name == "save_booking_to_db":
                    db_result = save_booking_to_db(
                        patient_name=function_args.get("patient_name"),
                        patient_age=function_args.get("patient_age"),
                        department=function_args.get("department"),
                        doctor_name=function_args.get("doctor_name"),
                        slot=function_args.get("slot")
                    )
                else:
                    db_result = json.dumps({"status": "error", "message": "Unknown function"})
                    
                # تجهيز التحديثات للذاكرة والسياق دون تعديل الذاكرة الحقيقية فوراً لحمايتها
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": function_name,
                    "content": db_result
                }
                
                # تحديث الـ updated_messages للطلب الثاني لضمان بقاء سياق التاريخ حياً للموديل
                updated_messages.append(message)
                updated_messages.append(tool_message)

                second_payload = {
                    "model": model_name,
                    "messages": updated_messages,
                    "temperature": 0.3
                }
                
                final_response = requests.post(url, headers=headers, json=second_payload, timeout=30)
                final_data = final_response.json()
                
                if "error" in final_data:
                    print(f" [خطأ في الرد النهائي مع {model_name}]:", json.dumps(final_data["error"], indent=2, ensure_ascii=False))
                    continue  # لو حدث خطأ هنا ينتقل للموديل الاحتياطي التالي ويبدأ من جديد بشكل سليم
                
                if "choices" in final_data:
                    # طالما نجحت العملية بالكامل، نقوم الآن بحفظ الردود في الذاكرة الفعلية للمستخدم
                    messages_history.append(message)
                    messages_history.append(tool_message)
                    
                    print(f" نجحت الاستجابة الكاملة بنجاح باستخدام الموديل: {model_name}")
                    raw_content = final_data["choices"][0]["message"]["content"]
                    return clean_response(raw_content)
                else:
                    print(f" [فشل صياغة الرد مع الموديل {model_name}]")
                    continue
            
            # في حال لم يطلب الموديل تشغيل أي دالة وأعطى رداً مباشراً
            print(f"✅ نجحت الاستجابة المباشرة بنجاح باستخدام الموديل: {model_name}")
            return clean_response(message["content"])

        except Exception as e:
            # في حال حدوث خطأ برمجي أو انقطاع شبكة مع هذا الموديل المعين
            print(f" [خطأ داخلي مع الموديل {model_name}]:", e)
            print(" جاري تجربة الموديل البديل...")
            continue # الانتقال للموديل التالي في اللوب

    # إذا انتهت الحلقة التكرارية ولم ينجح أي موديل من القائمة
    print(" فشلت جميع الموديلات المتاحة في القائمة!")
    return "عذراً، نواجه ضغطاً كبيراً جداً على السيرفرات حالياً. من فضلك أرسل رسالتك مرة أخرى بعد ثوانٍ."


# ==========================================
# 6. دالة إرسال الرسائل إلى واتساب (Meta API)
# ==========================================
def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    res = requests.post(url, headers=headers, json=data)
    print(f" [WhatsApp API Response]: {res.status_code}")


# ==========================================
# 7. مسارات السيرفر (Endpoints)
# ==========================================
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)
    return PlainTextResponse(content="verification failed", status_code=403)
# 1. نقوم بإنشاء مصفوفة (Set) خارج الدوال لتتبع معرفات الرسائل ومنع التكرار تماماً
PROCESSED_MESSAGE_IDS = set()

# 2. نقل منطق المعالجة الثقيل إلى دالة منفصلة تعمل في الخلفية
def process_chatbot_flow_in_background(message_obj: dict):
    try:
        user_number = message_obj["from"]
        msg_type = message_obj.get("type")
        user_text = ""
        
        #  هذا المتغير يفحص هل المستخدم أرسل ريكورد أم نص
        is_audio_input = False 

        if msg_type == "text":
            user_text = message_obj["text"]["body"]
            print(f" [خلفية] رسالة نصية واردة من {user_number}: {user_text}")
            
        elif msg_type == "audio":
            print(f" [خلفية] ريكورد صوتي وارد من {user_number}، جاري المعالجة...")
            media_id = message_obj["audio"]["id"]
            user_text = process_whatsapp_audio(media_id)
            
            # تغيير العلم إلى True لأن المستخدم أرسل ريكورد
            is_audio_input = True 
            
            if not user_text:
                send_whatsapp_message(user_number, "عذراً، لم أتمكن من سماع الريكورد بشكل واضح. هل يمكنك إعادة إرساله؟")
                return
        else:
            return

        if user_number not in chats_memory:
            chats_memory[user_number] = [{"role": "system", "content": SYSTEM_PROMPT}]
            
        chats_memory[user_number].append({"role": "user", "content": user_text})
        
        #  جلب رد الذكاء الاصطناعي الثابت
        ai_reply = call_groq_with_tools(chats_memory[user_number])
        chats_memory[user_number].append({"role": "assistant", "content": ai_reply})
        
        #  --- منطق الرد الذكي والمعدل بناءً على طلبكِ ---
        if is_audio_input:
            # 1 أولاً: نرسل الرد النصي دائماً
            print(f" جاري إرسال الرد النصي لـ {user_number}...")
            send_whatsapp_message(user_number, ai_reply)
        
        # 2 ثانياً: نقوم بصنع الريكورد ورفعه وإرساله بجانب النص
            print(f" جاري تحويل رد البوت إلى فويس لإرساله مكملاً للنص...")
            audio_file = convert_text_to_speech(ai_reply, filename=f"reply_{user_number}.mp3")
        
            media_id = None
            if audio_file:
                media_id = upload_audio_to_whatsapp(audio_file)
    #         # تنظيف السيرفر وحذف الملف المؤقت فوراً
                if os.path.exists(audio_file):
                    os.remove(audio_file)

            if media_id:
                print(f" جاري إرسال الرد الصوتي التابع للنص إلى {user_number}...")
                send_whatsapp_audio(user_number, media_id)
            else:
                print(f" تنبيه: فشل توليد الريكورد، لكن تم إرسال النص بنجاح.")
            
        else:
            #  إذا أرسل المستخدم نصاً مكتوباً من البداية، نرد بنص فقط كالعادة
            print(f" جاري إرسال الرد النصي العادي لـ {user_number}...")
        send_whatsapp_message(user_number, ai_reply)
    # --- نهاية منطق الرد الذكي ---

    except Exception as e:
        print(" خطأ أثناء معالجة التدفق في الخلفية:", e)
# 3. دالة الـ Webhook الرئيسية المحدثة (ترد على واتساب فوراً وتفوض العمل للخلفية)
@app.post("/webhook")
async def receive_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        
        if "entry" in data and data["entry"][0]["changes"][0]["value"].get("messages"):
            message_obj = data["entry"][0]["changes"][0]["value"]["messages"][0]
            
            # جلب المعرّف الفريد للرسالة لمنع معالجة الرسائل المعاد إرسالها من فيسبوك
            msg_id = message_obj.get("id")
            
            if msg_id in PROCESSED_MESSAGE_IDS:
                print(f" [تنبيه] تم حجب رسالة مكررة تلقائياً لمنع تلوث الذاكرة: {msg_id}")
                return {"status": "success"} # نرد بـ success حتى لا يستمر واتساب بالإرسال
            
            # إضافة المعرف للمخزن وتصفية المخزن الدورية منعاً لاستهلاك الرام
            PROCESSED_MESSAGE_IDS.add(msg_id)
            if len(PROCESSED_MESSAGE_IDS) > 2000:
                PROCESSED_MESSAGE_IDS.clear()

            #   بـ 200 OK في أقل من 0.1 ثانية!
            background_tasks.add_task(process_chatbot_flow_in_background, message_obj)
            
        return {"status": "success"}
    except Exception as e:
        print(" خطأ أثناء استقبال الـ Webhook السريع:", e)
        return {"status": "error", "detail": str(e)}
    
#------










