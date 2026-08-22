import asyncio
import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_user, get_user, update_credits, get_settings, settings_col, users_col
from server import web_server

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", 123456))
API_HASH = os.environ.get("API_HASH")

app = Client("VideoBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- AUTO DELETE TASK ---
async def auto_delete_message(chat_id, message_id, delay=300):
    """5 minute (300 sec) baad video auto-delete karega"""
    await asyncio.sleep(delay)
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

# --- CHECK FORCE SUB ---
async def is_subscribed(user_id, channel_username):
    try:
        member = await app.get_chat_member(channel_username, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# --- START COMMAND & REFERRAL ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user_id = message.from_user.id
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    
    settings = await get_settings()
    main_fsub = settings.get("main_fsub")
    
    # 1. Check Main Force Sub
    if main_fsub and not await is_subscribed(user_id, main_fsub):
        btn = [[InlineKeyboardButton("📢 Join Channel To Unlock", url=f"https://t.me/{main_fsub.replace('@', '')}")],
               [InlineKeyboardButton("✅ I Have Joined", callback_data="check_main_fsub")]]
        await message.reply_text("👋 **Welcome!**\n\nFree videos dekhne ke liye pehle hamara official channel join karein! 👇", reply_markup=InlineKeyboardMarkup(btn))
        return

    # 2. Register User & Handle Referral
    is_new = await add_user(user_id, referrer_id)
    if is_new and referrer_id:
        # Give 20 credits to Referrer when new user joins and completes FSub
        await update_credits(referrer_id, 20)
        try:
            await app.send_message(referrer_id, "🎉 **Congratulations!**\nAapke referral link se ek dost ne join kiya hai. Aapko **20 Free Videos** mil gaye hain! 🎁")
        except: pass

    # 3. Welcome Message
    btn = [[InlineKeyboardButton("🎬 Start Watching Free Videos", callback_data="watch_vid")]]
    await message.reply_text("🎉 **Account Verified!**\n\nAapko **10 Free Videos** ka credit mil chuka hai. Niche button daba kar dekhna shuru karein! 🍿", reply_markup=InlineKeyboardMarkup(btn))


# --- VIDEO STREAMING & SEQUENTIAL FSUB ---
@app.on_callback_query()
async def callback_handler(client, query):
    user_id = query.from_user.id
    data = query.data
    user = await get_user(user_id)
    settings = await get_settings()

    if data == "watch_vid" or data == "next_vid":
        # 1. Check Credits
        if user['credits'] <= 0:
            # Trigger Sequential Force Sub
            channels = settings.get("credit_channels", [])
            claimed = user.get("claimed_channels", [])
            
            next_channel = None
            for ch in channels:
                if ch not in claimed:
                    next_channel = ch
                    break
            
            if next_channel:
                btn = [[InlineKeyboardButton("📢 Join For +30 Videos", url=f"https://t.me/{next_channel.replace('@', '')}")],
                       [InlineKeyboardButton("✅ Verify Join", callback_data=f"verify_{next_channel}")]]
                await query.message.edit_text(f"⚠️ **Free Credits Khatam!**\n\nAage ki **30 videos** dekhne ke liye iss naye channel ko join karein 👇", reply_markup=InlineKeyboardMarkup(btn))
            else:
                await query.message.edit_text("🚫 **Saare Tasks Khatam!**\n\nNaye channels aane ka wait karein ya apne doston ko refer karke 20 credits/refer kamayein!\n\n🔗 Your Ref Link: `https://t.me/YourBotName?start={user_id}`")
            return

        # 2. Send Video (Deduct Credit)
        if data == "next_vid":
            await update_credits(user_id, -1)
            # Update current video number in DB
            await users_col.update_one({"_id": user_id}, {"$inc": {"current_video_id": 1}})
            user = await get_user(user_id) # Refresh data

        vid_no = user['current_video_id']
        source = settings.get("source_channel")
        
        try:
            # Fetch video message from source channel
            vid_msg = await app.get_messages(source, vid_no)
            
            buttons = [
                [InlineKeyboardButton("⏮ Prev", callback_data="prev_vid"), InlineKeyboardButton(f"📺 Vid {vid_no}", callback_data="noop"), InlineKeyboardButton("Next ⏭", callback_data="next_vid")],
                [InlineKeyboardButton("👍", callback_data="react"), InlineKeyboardButton("❤️", callback_data="react"), InlineKeyboardButton("🔥", callback_data="react")],
                [InlineKeyboardButton("💾 Save Video", callback_data=f"save_{vid_no}"), InlineKeyboardButton("👑 Premium", callback_data="premium")]
            ]
            
            # Send Video
            sent_msg = await vid_msg.copy(chat_id=user_id, reply_markup=InlineKeyboardMarkup(buttons))
            await query.message.delete() # Pura message delete kar do

            # Start Auto Delete Timer (5 min)
            asyncio.create_task(auto_delete_message(user_id, sent_msg.id, 300))
            
        except Exception as e:
            await query.answer("Video upload ho rahi hai, thodi der baad try karein!", show_alert=True)


    # --- VERIFY SEQUENTIAL FSUB ---
    elif data.startswith("verify_"):
        channel_to_verify = data.split("_")[1]
        if await is_subscribed(user_id, channel_to_verify):
            await users_col.update_one(
                {"_id": user_id}, 
                {"$inc": {"credits": 30}, "$push": {"claimed_channels": channel_to_verify}}
            )
            await query.answer("🎉 30 Videos Unlocked!", show_alert=True)
            await query.message.edit_text("✅ Verification Successful! Niche dabakar aage dekhein.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Continue Watching", callback_data="watch_vid")]]))
        else:
            await query.answer("❌ Aapne abhi tak channel join nahi kiya hai!", show_alert=True)

# --- START APP & SERVER ---
if __name__ == "__main__":
    app.start()
    print("Bot Started!")
    # Start Dummy Server for Koyeb
    loop = asyncio.get_event_loop()
    loop.run_until_complete(web_server())
    loop.run_forever()
