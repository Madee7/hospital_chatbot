import os
import asyncio
import requests
import edge_tts
from dotenv import load_dotenv  
import re

load_dotenv()

# جلب متغيرات البيئة في النطاق العام لدوال الملف
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# رابط سيرفر الـ FastAPI الخاص بكِ الذي يشغل نموذج EgypTalk-ASR-v2 المخصص
EGYPTALK_SERVER_URL = "http://localhost:8000/transcribe"


def process_whatsapp_audio(media_id: str) -> str:
    """
    1. تجلب رابط الريكورد من Meta باستخدام الـ media_id.
    2. تحميل ملف الصوت وحفظه مؤقتاً.
    3. إرساله إلى سيرفر EgypTalk-ASR-v2 المحلي لتقليل الـ Egyptian WER.
    4. تنظيف السيرفر بحذف الملف المؤقت وإرجاع النص العامي الدقيق.
    """
    if not WHATSAPP_TOKEN:
        print(" عذراً، مفتاح WHATSAPP_TOKEN غير مكتمل في ملف بيئة العمل.")
        return ""

    try:
        # الخطوة 1: طلب معلومات ملف الصوت ورابط تحميله من Meta
        media_url = f"https://graph.facebook.com/v20.0/{media_id}"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        
        response = requests.get(media_url, headers=headers, timeout=15)
        media_data = response.json()
        
        download_url = media_data.get("url")
        if not download_url:
            print(" لم يتم العثور على رابط تحميل الصوت من Meta API")
            return ""

        # الخطوة 2: تحميل ملف الصوت الفعلي وحفظه مؤقتاً
        audio_response = requests.get(download_url, headers=headers, timeout=20)
        
        # نستخدم امتداد الصوت القادم من العميل (غالباً ogg أو aac)
        temp_filename = f"temp_voice_{media_id}.ogg"
        
        with open(temp_filename, "wb") as f:
            f.write(audio_response.content)
        
        # الخطوة 3: إرسال الملف الصوتي إلى سيرفر EgypTalk المخصص بدلاً من Groq Whisper
        print(f" [ASR] جاري إرسال الريكورد إلى سيرفر EgypTalk-ASR-v2...")
        
        with open(temp_filename, "rb") as audio_file:
            files = {"file": (temp_filename, audio_file, "audio/ogg")}
            
            # استدعاء السيرفر المحلي الخاص بكِ
            egyptalk_response = requests.post(EGYPTALK_SERVER_URL, files=files, timeout=45)
            
        print(" EgypTalk Server Status Code:", egyptalk_response.status_code)
        
        # تنظيف وحذف ملف الصوت المؤقت من الـ Webhook سيرفر
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
        if egyptalk_response.status_code == 200:
            res_data = egyptalk_response.json()
            transcribed_text = res_data.get("transcription", "")
            print(f" [نص الريكورد المستخرج بنجاح عبر EgypTalk]: {transcribed_text}")
            return transcribed_text.strip()
        else:
            print(f" تفاصيل خطأ سيرفر تفريغ الصوت: {egyptalk_response.text}")
            return ""

    except Exception as e:
        print(f" خطأ أثناء معالجة الحزمة الصوتية: {e}")
        if 'temp_filename' in locals() and os.path.exists(temp_filename):
            os.remove(temp_filename)
        return ""


def convert_text_to_speech(text: str, filename: str) -> str:
    """
    تحويل النص إلى صوت مع معالجة الاختصارات العربية (د. / ود.) بأمان وبدون أخطاء Regex.
    """
    print(f" [TTS] النص الأصلي المستلم قبل المعالجة: {text}")

    # 1 استبدال د. أو ود. أو فد. بـ دكتور بشكل آمن تماماً باستخدام المجموعات (Capturing Groups)
    cleaned_text = re.sub(r'(^|\s)([وفبل]?)د\.', r'\1\2دكتور ', text)
    
    # 2 معالجة تنوين "صباحاً" و "مساءً" لمنع تكرار المحرك الصوتي
    cleaned_text = cleaned_text.replace("صباحاً", "صباحا").replace("مساءً", "مساء")
    
    # 3 تنظيف أي مسافات زائدة
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    print(f" [TTS] النص النهائي الموجه للمحرك الصوتي: {cleaned_text}")

    async def _generate():
        # استخدام الصوت البشري الطبيعي شاكر
        communicate = edge_tts.Communicate(cleaned_text, "ar-EG-ShakirNeural")
        await communicate.save(filename)

    try:
        asyncio.run(_generate())
        print(f" [Edge-TTS] تم توليد ملف الصوت بنجاح: {filename}")
        return filename
    except Exception as e:
        print(f" خطأ في تحويل النص إلى صوت: {e}")
        return None


def upload_audio_to_whatsapp(audio_file_path: str) -> str:
    """
    رفع ملف الصوت إلى سيرفرات Meta للحصول على media_id
    """
    if not PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        print(" خطأ: PHONE_NUMBER_ID أو WHATSAPP_TOKEN غير معرفين لدالة الرفع.")
        return None
        
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    try:
        with open(audio_file_path, "rb") as f:
            files = {
                "file": (os.path.basename(audio_file_path), f, "audio/mpeg"), 
                "messaging_product": (None, "whatsapp")
            }
            response = requests.post(url, headers=headers, files=files)
            
        if response.status_code == 200:
            return response.json().get("id")
        else:
            print(f" فشل رفع الصوت إلى واتساب: {response.text}")
            return None
    except Exception as e:
        print(f" خطأ أثناء رفع ملف الصوت: {e}")
        return None


def send_whatsapp_audio(to_number: str, media_id: str):
    """
    إرسال ملف الصوت للمستخدم النهائي عبر الواتساب.
    """
    if not PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        print(" خطأ: PHONE_NUMBER_ID أو WHATSAPP_TOKEN غير معرفين.")
        return None
        
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "audio", 
        "audio": {"id": media_id}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f" [WhatsApp API Response]: {response.status_code}")
        if response.status_code != 200:
            print(f" تفاصيل خطأ سيرفر Meta: {response.text}")
        return response.json()
    except Exception as e:
        print(f" خطأ في إرسال رسالة الصوت: {e}")
        return None