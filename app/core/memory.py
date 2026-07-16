# حفظ المحادثات لكل مستخدم أثناء تشغيل السيرفر
chats_memory = {}

# منع معالجة نفس رسالة WhatsApp أكثر من مرة
PROCESSED_MESSAGE_IDS = set()