import os
import string
import random
import asyncio
import sys
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ================= CONFIGURATION =================
API_ID = 34833810
API_HASH = "6b16568fca91a646a2e2e1cae94f5bb6"
BOT_TOKEN = "8501752321:AAFmSLnhtO0jdlLyyrtPKdPFnL1nVPUkdDk"

# অ্যাডমিন লিস্ট
ADMIN_IDS = [6872143322, 8363437161]

# MongoDB URL
MONGO_URL = "mongodb+srv://atkcyber5_db_user:adminabir221@cluster0.4iwef3e.mongodb.net/?appName=Cluster0"

# ================= BOT CLIENT (Fix for Render) =================
app = Client(
    "my_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=10,
    in_memory=True  # ⚠️ এটি Render-এ সেশন ফাইল সমস্যা সমাধান করবে
)

# গ্লোবাল ভেরিয়েবল
temp_data = {}
mongo_client = None
collection = None

# ================= HELPER FUNCTIONS =================
def generate_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def generate_pass(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# ================= DATABASE CONNECTION =================
async def init_db():
    global mongo_client, collection
    print("⏳ Connecting to MongoDB...", flush=True)
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        db = mongo_client["FileShareBot"]
        collection = db["files"]
        await mongo_client.admin.command('ping')
        print("✅ MongoDB Connected Successfully!", flush=True)
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}", flush=True)
        print("⚠️ Check MongoDB Atlas IP Access", flush=True)

# ================= BOT COMMANDS =================

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    # ডিবাগিং: মেসেজ আসলে লগে দেখাবে
    print(f"📩 Message Received from: {message.from_user.first_name} (ID: {message.from_user.id})", flush=True)
    
    user_id = message.from_user.id
    
    if collection is None:
        await message.reply_text("❌ Database Error! Admin check logs.")
        return

    if len(message.command) > 1:
        unique_id = message.command[1]
        file_data = await collection.find_one({"_id": unique_id})
        
        if file_data:
            limit = file_data.get("limit", 0)
            used = file_data.get("used", 0)

            if limit > 0 and used >= limit:
                await message.reply_text("❌ **লিংকের মেয়াদ শেষ!**")
                return

            await message.reply_text("🔒 **ফাইলটি লক করা!**\n\n👇 নিচে পাসওয়ার্ডটি লিখুন:", quote=True)
            temp_data[f"wait_pass_{user_id}"] = unique_id
        else:
            await message.reply_text("❌ ফাইলটি পাওয়া যায়নি।")
        return

    # অ্যাডমিন প্যানেল
    if user_id in ADMIN_IDS:
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data="stats"), InlineKeyboardButton("ℹ️ হেল্প", callback_data="help")]
        ])
        await message.reply_text(
            f"⚡ **অ্যাডমিন প্যানেল**\n\n"
            "ফাইল শেয়ার করতে ফাইল, ভিডিও বা ছবি সেন্ড করুন।",
            reply_markup=buttons
        )
    else:
        await message.reply_text(f"হ্যালো {message.from_user.first_name}! 👋\nআমি ফাইল শেয়ারিং বট।")

# ফাইল হ্যান্ডলার (Admin)
@app.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo) & filters.user(ADMIN_IDS))
async def handle_file(client, message: Message):
    print(f"📂 File Received from Admin: {message.from_user.id}", flush=True)
    
    file_id = None
    if message.photo: file_id = message.photo[-1].file_id
    elif message.video: file_id = message.video.file_id
    elif message.audio: file_id = message.audio.file_id
    elif message.document: file_id = message.document.file_id
    
    if not file_id: return
    
    temp_data[f"setup_{message.from_user.id}"] = {"file_id": file_id}
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ কাস্টম পাস", callback_data="set_custom_pass"), InlineKeyboardButton("🎲 অটো পাস", callback_data="set_auto_pass")],
        [InlineKeyboardButton("❌ বাতিল", callback_data="cancel_process")]
    ])
    await message.reply_text("📂 **ফাইল রিসিভ হয়েছে!**", reply_markup=buttons, quote=True)

# কলব্যাক হ্যান্ডলার
@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if user_id not in ADMIN_IDS and data != "help": 
        return await callback_query.answer("Only Admin!", show_alert=True)

    if data == "set_custom_pass":
        temp_data[f"mode_{user_id}"] = "waiting_custom_pass"
        await callback_query.message.edit_text("✍️ **পাসওয়ার্ড লিখুন:**")

    elif data == "set_auto_pass":
        temp_data[f"setup_{user_id}"]["password"] = generate_pass()
        await ask_limit(callback_query.message)

    elif data.startswith("limit_"):
        if data == "limit_custom":
            temp_data[f"mode_{user_id}"] = "waiting_custom_limit"
            await callback_query.message.edit_text("🔢 **কতজন? (সংখ্যা):**")
        else:
            limit_val = int(data.split("_")[1])
            await finalize_upload(client, callback_query.message, user_id, limit_val)

    elif data == "cancel_process":
        temp_data.pop(f"setup_{user_id}", None)
        await callback_query.message.delete()

    elif data == "stats":
        if collection:
            total = await collection.count_documents({})
            await callback_query.answer(f"📊 মোট ফাইল: {total}", show_alert=True)
        else:
            await callback_query.answer("Database Error!", show_alert=True)

async def ask_limit(message):
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("∞ আনলিমিটেড", callback_data="limit_0"), InlineKeyboardButton("১ জন", callback_data="limit_1"), InlineKeyboardButton("কাস্টম", callback_data="limit_custom")]])
    await message.edit_text("🚧 **লিমিট কত?**", reply_markup=buttons)

async def finalize_upload(client, message, user_id, limit):
    if collection is None: return
    setup = temp_data.get(f"setup_{user_id}")
    if not setup: return
    unique_id = generate_id()
    await collection.insert_one({"_id": unique_id, "file_id": setup["file_id"], "password": setup["password"], "limit": limit, "used": 0})
    del temp_data[f"setup_{user_id}"]
    bot_username = (await client.get_me()).username
    link = f"https://t.me/{bot_username}?start={unique_id}"
    await message.edit_text(f"✅ **Done!**\n🔗 `{link}`\n🔑 `{setup['password']}`")

# টেক্সট হ্যান্ডলার
@app.on_message(filters.text & filters.private)
async def handle_text(client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    mode = temp_data.get(f"mode_{user_id}")

    if mode == "waiting_custom_pass":
        temp_data[f"setup_{user_id}"]["password"] = text
        await ask_limit(message)
    elif mode == "waiting_custom_limit":
        if text.isdigit(): await finalize_upload(client, message, user_id, int(text))
    elif f"wait_pass_{user_id}" in temp_data:
        if collection is None: return
        unique_id = temp_data[f"wait_pass_{user_id}"]
        file_data = await collection.find_one({"_id": unique_id})
        if file_data and file_data['password'] == text:
            del temp_data[f"wait_pass_{user_id}"]
            asyncio.create_task(collection.update_one({"_id": unique_id}, {"$inc": {"used": 1}}))
            await client.send_cached_media(message.chat.id, file_data['file_id'], caption="✅ ফাইল।")
        else:
            await message.reply_text("❌ ভুল পাসওয়ার্ড!")

# ================= RUNNER =================
async def main():
    # 1. Web Server
    print("🌍 Web Server Init...", flush=True)
    async def handle(request): return web.Response(text="Bot Live")
    app_web = web.Application()
    app_web.router.add_get("/", handle)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    print("✅ Web Server Running", flush=True)

    # 2. Database
    await init_db()

    # 3. Bot Start
    print("🤖 Starting Bot Client...", flush=True)
    try:
        await app.start()
        print("✅ BOT STARTED SUCCESSFULLY! (Ready to reply)", flush=True)
        await idle()
    except Exception as e:
        print(f"❌ Bot Start Error: {e}", flush=True)
    finally:
        await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
