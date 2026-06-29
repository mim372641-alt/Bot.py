import subprocess
import sys
import asyncio
import sqlite3
import time
import datetime

# --- AUTOMATIC PACKAGE INSTALLER ---
try:
    import aiogram
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiogram"])

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand, TelegramObject
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ======================== CONFIGURATION ========================
BOT_TOKEN = "8995844901:AAFdpfYcEPxzpBX2PvDUYR0tQMkVYWVaSfI"  # <--- আপনার বটের টোকেন
ADMIN_ID = 8529906939               # <--- আপনার টেলিগ্রাম আইডি
REFERRAL_BONUS = 5.0               # প্রতি রেফারে ৫ টাকা বোনাস

# 💰 পেমেন্ট নাম্বারসমূহ 💰
BKASH_NUMBER = "01993148177 (Send Money)"
NAGAD = "01993148177 (Send Money)"
ROCKET_NUMBER = "01993148177 (Send Money)"
BINANCE_ID = "1170076628 (Pay ID)"

# ===== FORCE JOIN (৩টি চ্যানেল) =====
CHANNEL_1 = ""
CHANNEL_2 = ""
CHANNEL_3 = ""  # <--- আপনার ৩ নম্বর চ্যানেলের ইউজারনেম এখানে দিন
# ===============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- ANTI-SPAM MEMORY STORAGE ---
user_clicks = {}    # {user_id: [timestamps]}
blocked_users = {}  # {user_id: unblock_timestamp}
active_deposits = {}  # {admin_msg_id: {"user_id": int, "status": str}}

# --- GLOBAL BUTTONS LIST FOR SMART RESET ---
MENU_BUTTONS = {
    "🛒 Panel Shop", "💰 Add Money", "👤 Balance Check", 
    "👥 Refer & Earn", "🔑 My Keys", "📞 Support", "🛡️ Admin Panel",
    "⚙️ Manage Shop", "💵 Credit Balance", "✉️ User Personal Chat", 
    "📢 Broadcast Notice", "📋 Pending Orders", "🗑️ Delete Broadcasts", 
    "🔍 Check User Balance", "🔙 Back to User Menu"
}

# --- MIDDLEWARE: STATE RESET ON MENU BUTTON CLICK ---
class StateResetMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message) and event.text:
            if event.text in MENU_BUTTONS:
                state: FSMContext = data.get("state")
                if state:
                    await state.clear()
        return await handler(event, data)

# --- MIDDLEWARE: PURE ASYNC ANTI-SPAM (USES ZERO THREADS) ---
class AntiSpamMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if not user or user.id == ADMIN_ID:
            return await handler(event, data)
            
        user_id = user.id
        user_name = user.full_name
        current_time = time.time()
        
        if user_id in blocked_users:
            if current_time < blocked_users[user_id]:
                remaining = int(blocked_users[user_id] - current_time)
                msg = f"❌ You are blocked for spamming! Try again after {remaining // 60}m {remaining % 60}s."
                if isinstance(event, CallbackQuery):
                    await event.answer(msg, show_alert=True)
                elif isinstance(event, Message):
                    await event.answer(msg)
                return
            else:
                del blocked_users[user_id]

        if user_id not in user_clicks:
            user_clicks[user_id] = []
            
        user_clicks[user_id].append(current_time)
        user_clicks[user_id] = [t for t in user_clicks[user_id] if current_time - t <= 5]

        if len(user_clicks[user_id]) >= 6:
            blocked_users[user_id] = current_time + 600
            user_clicks[user_id] = []
            
            asyncio.create_task(send_spam_alert_to_admin(user_id, user_name))
            msg = "🚨 Stop Spamming! You have been blocked for 10 minutes."
            if isinstance(event, CallbackQuery):
                await event.answer(msg, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(msg)
            return
            
        return await handler(event, data)

async def send_spam_alert_to_admin(user_id: int, user_name: str):
    unblock_btn = [[InlineKeyboardButton(text="🔓 Unblock User", callback_data=f"unban_{user_id}")]]
    try:
        await bot.send_message(
            ADMIN_ID, 
            f"🚨 <b>Spam Alert!</b>\n\n"
            f"👤 User: {user_name}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"⚠️ Status: Auto-blocked for 10 minutes.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=unblock_btn)
        )
    except: pass

# Registering Middlewares
dp.message.outer_middleware(StateResetMiddleware())
dp.message.middleware(AntiSpamMiddleware())
dp.callback_query.middleware(AntiSpamMiddleware())


# --- CUSTOM PURE ASYNC MOCK LAYER FOR PURE SQLITE3 ---
db_connection = None

class DummyExecutor:
    def __init__(self, conn, sql, parameters):
        self.conn = conn
        self.sql = sql
        self.parameters = parameters
        self.cursor = None

    def __await__(self):
        self.cursor = self.conn.cursor()
        self.cursor.execute(self.sql, self.parameters)
        async def _return_self():
            return self
        return _return_self().__await__()

    async def __aenter__(self):
        self.cursor = self.conn.cursor()
        self.cursor.execute(self.sql, self.parameters)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()

    async def fetchone(self):
        return self.cursor.fetchone()

    async def fetchall(self):
        return self.cursor.fetchall()

class DummyConnection:
    def __init__(self, conn):
        self.conn = conn
    def execute(self, sql, parameters=()):
        return DummyExecutor(self.conn, sql, parameters)
    async def commit(self):
        self.conn.commit()
    async def close(self):
        self.conn.close()

class DatabaseContext:
    async def __aenter__(self):
        global db_connection
        if db_connection is None:
            db_connection = sqlite3.connect("database.db", check_same_thread=False)
            db_connection.execute("PRAGMA journal_mode=WAL;")
        return DummyConnection(db_connection)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

def get_db():
    return DatabaseContext()


# --- FSM STATES ---
class BotStates(StatesGroup):
    submit_payment_proof = State()
    create_product_main = State() 
    add_plan_duration = State()   
    add_plan_price = State()      
    edit_plan_dur = State()       
    edit_plan_prc = State()       
    admin_credit_id = State()     
    admin_credit_amt = State()    
    admin_msg_id = State()        
    admin_msg_text = State()      
    admin_broadcast = State()     
    input_license_key = State()   
    deposit_load_amt = State()    
    admin_check_user_id = State() 

# --- KEYBOARDS ---
def main_menu_keyboard(user_id: int):
    buttons = [
        [KeyboardButton(text="🛒 Panel Shop"), KeyboardButton(text="💰 Add Money")],
        [KeyboardButton(text="👤 Balance Check"), KeyboardButton(text="👥 Refer & Earn")],
        [KeyboardButton(text="🔑 My Keys"), KeyboardButton(text="📞 Support")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([KeyboardButton(text="🛡️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_panel_keyboard():
    buttons = [
        [KeyboardButton(text="⚙️ Manage Shop"), KeyboardButton(text="💵 Credit Balance")],
        [KeyboardButton(text="✉️ User Personal Chat"), KeyboardButton(text="📢 Broadcast Notice")],
        [KeyboardButton(text="📋 Pending Orders"), KeyboardButton(text="🗑️ Delete Broadcasts")],
        [KeyboardButton(text="🔍 Check User Balance")],  
        [KeyboardButton(text="🔙 Back to User Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


async def is_user_joined(user_id):
    try:
        member1 = await bot.get_chat_member(CHANNEL_1, user_id)
        member2 = await bot.get_chat_member(CHANNEL_2, user_id)
        member3 = await bot.get_chat_member(CHANNEL_3, user_id)
        allowed = ["member", "administrator", "creator"]
        return member1.status in allowed and member2.status in allowed and member3.status in allowed
    except:
        return False


# --- DATABASE SETUP ---
async def init_db():
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, 
                balance REAL DEFAULT 0.0, 
                status TEXT DEFAULT 'active',
                referred_by INTEGER DEFAULT NULL
            )
        """)
        await db.execute("CREATE TABLE IF NOT EXISTS main_products (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT UNIQUE)")
        await db.execute("CREATE TABLE IF NOT EXISTS plans (id INTEGER PRIMARY KEY AUTOINCREMENT, product_name TEXT, duration TEXT, price REAL)")
        await db.execute("CREATE TABLE IF NOT EXISTS pending_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, product TEXT, price REAL, order_time TEXT, plan_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS broadcast_logs (user_id INTEGER, message_id INTEGER)")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS delivered_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                product_name TEXT,
                license_key TEXT,
                delivery_time TEXT
            )
        """)
        await db.commit()


# --- ADMIN UNBLOCK HANDLER ---
@dp.callback_query(F.data.startswith("unban_"))
async def admin_unblock_user(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    target_uid = int(callback.data.split("_")[1])
    
    if target_uid in blocked_users:
        del blocked_users[target_uid]
        if target_uid in user_clicks:
            user_clicks[target_uid] = []
        
        await callback.message.edit_text(f"✅ User <code>{target_uid}</code> has been successfully unblocked!", parse_mode="HTML")
        try:
            await bot.send_message(target_uid, "🔓 <b>Good News!</b>\nAdmin has manually unblocked you. Please use the bot responsibly now.", parse_mode="HTML")
        except: pass
    else:
        await callback.answer("This user is already active or their block duration expired.", show_alert=True)

# --- START COMMAND ---
@dp.message(CommandStart())
@dp.message(Command("start"))
@dp.message(F.text == "🔙 Back to User Menu")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    joined = await is_user_joined(user_id)

   if not joined:
 #      keyboard = InlineKeyboardMarkup(
 #          inline_keyboard=[
 #               [InlineKeyboardButton(text="📢 Join Channel 1", url=f"https://t.me/{CHANNEL_1.replace('@','')}")],
 #               [InlineKeyboardButton(text="📢 Join Channel 2", url=f"https://t.me/{CHANNEL_2.replace('@','')}")],
 #               [InlineKeyboardButton(text="📢 Join Channel 3", url=f"https://t.me/{CHANNEL_3.replace('@','')}")],
 #               [InlineKeyboardButton(text="✅ Check Join", callback_data="check_join")]
 #           ]
 #      )
 #      await message.answer(
 #           "🚫 Before using this bot you must join all three channels.",
 #           reply_markup=keyboard
 #       )
 #       return
    
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])

    async with get_db() as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_exists = await cursor.fetchone()

        if not user_exists:
            if referrer_id and referrer_id != user_id:
                await db.execute("INSERT INTO users (user_id, referred_by) VALUES (?, ?)", (user_id, referrer_id))
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (REFERRAL_BONUS, referrer_id))
                await db.commit()
                try:
                    await bot.send_message(referrer_id, f"🎉 <b>New Referral!</b>\nSomeone joined using your link. You earned <code>+{REFERRAL_BONUS} Tk</code>!", parse_mode="HTML")
                except Exception: pass
            else:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                
    await message.answer("👋 Welcome! Select an option from the menu below:", reply_markup=main_menu_keyboard(user_id))

# --- ADMIN PANEL MAIN ---
@dp.message(F.text == "🛡️ Admin Panel")
async def admin_main_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    await message.answer("🛡️ <b>Admin Dashboard Activated:</b>", reply_markup=admin_panel_keyboard(), parse_mode="HTML")

# --- REFER & EARN ---
@dp.message(F.text == "👥 Refer & Earn")
async def refer_and_earn(message: Message):
    user_id = message.from_user.id
    bot_info = await bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE referred_by = ?", (user_id,)) as cursor:
            total_refers = (await cursor.fetchone())[0]

    share_text = (
        f"🎁 <b>Refer & Earn Program</b>\n\n"
        f"🔗 <b>Your Invite Link:</b>\n<code>{invite_link}</code>\n\n"
        f"💰 <b>Reward:</b> Share this link. When a new user starts the bot via your link, you will instantly get <code>{REFERRAL_BONUS} Tk</code>!\n"
        f"⚠️ <b>Note:</b> Re-inviting old/existing users will not grant any bonus.\n\n"
        f"📊 <b>Your Stats:</b> Total valid refers: <code>{total_refers}</code> users."
    )
    await message.answer(share_text, parse_mode="HTML")

# --- ⚙️ SHOP MANAGEMENT ---
@dp.message(F.text == "⚙️ Manage Shop")
async def manage_shop_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    buttons = [
        [InlineKeyboardButton(text="🆕 Create Product Category", callback_data="adm_newprod")],
        [InlineKeyboardButton(text="➕ Add Plan to Category", callback_data="adm_addplan")],
        [InlineKeyboardButton(text="✏️ Edit / Delete Items", callback_data="adm_editlist")]
    ]
    await message.answer("⚙️ <b>Shop Inventory Control:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "adm_editlist")
async def show_editing_categories(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with get_db() as db:
        async with db.execute("SELECT id, product_name FROM main_products") as cursor: prods = await cursor.fetchall()
    buttons = []
    for p in prods:
        buttons.append([InlineKeyboardButton(text=p[1], callback_data=f"ecat_{p[0]}"), InlineKeyboardButton(text="🗑️ Delete Cat", callback_data=f"dcat_{p[0]}")])
    await callback.message.edit_text("✏️ Select category to manage plans:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("ecat_"))
async def view_plans_for_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    cid = int(callback.data.split("_")[1])
    async with get_db() as db:
        async with db.execute("SELECT product_name FROM main_products WHERE id = ?", (cid,)) as cursor: row = await cursor.fetchone()
        if not row:
            await callback.answer("Category not found.")
            return
        pname = row[0]
        async with db.execute("SELECT id, duration, price FROM plans WHERE product_name = ?", (pname,)) as cursor: plans = await cursor.fetchall()
    
    buttons = []
    for pl in plans:
        buttons.append([InlineKeyboardButton(text=f"⏱️ Edit Name: {pl[1]}", callback_data=f"edname_{pl[0]}")])
        buttons.append([InlineKeyboardButton(text=f"💵 Edit Price: {pl[2]} Tk", callback_data=f"edprc_{pl[0]}")])
        buttons.append([InlineKeyboardButton(text="🗑️ Delete Plan", callback_data=f"dplan_{pl[0]}")])
        buttons.append([InlineKeyboardButton(text="----------------------------------", callback_data="void")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="adm_editlist")])
    await callback.message.edit_text(f"📝 <b>Category:</b> {pname}\nClick a button below to edit:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("edname_"))
async def route_edit_name(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split("_")[1])
    await state.update_data(edit_pid=pid)
    await state.set_state(BotStates.edit_plan_dur)
    await callback.message.answer("✍️ Enter <b>NEW</b> Plan Name/Duration:", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("edprc_"))
async def route_edit_price(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split("_")[1])
    await state.update_data(edit_pid=pid)
    await state.set_state(BotStates.edit_plan_prc)
    await callback.message.answer("✍️ Enter <b>NEW</b> Price Amount (Numbers only):", parse_mode="HTML")
    await callback.answer()

@dp.message(BotStates.edit_plan_dur)
async def save_edit_dur(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    pid = data.get('edit_pid')
    
    async with get_db() as db:
        await db.execute("UPDATE plans SET duration = ? WHERE id = ?", (message.text, pid))
        await db.commit()
    await message.answer(f"✅ Saved! Updated name to: <code>{message.text}</code>", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    await state.clear()

@dp.message(BotStates.edit_plan_prc)
async def save_edit_prc(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    clean_text = message.text.replace('.', '', 1).strip()
    if not clean_text.isdigit():
        await message.answer("❌ Numbers only. Enter valid price:")
        return
        
    data = await state.get_data()
    pid = data.get('edit_pid')
    new_price = float(message.text)
    
    async with get_db() as db:
        await db.execute("UPDATE plans SET price = ? WHERE id = ?", (new_price, pid))
        await db.commit()
    await message.answer(f"✅ Saved! Updated price to: <code>{new_price} Tk</code>", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    await state.clear()

# --- ✉️ USER PERSONAL CHAT ---
@dp.message(F.text == "✉️ User Personal Chat")
async def admin_chat_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_msg_id)
    await message.answer("🆔 Enter target Telegram User ID:")

@dp.message(BotStates.admin_msg_id)
async def process_chat_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.isdigit():
        await message.answer("❌ Invalid ID. Enter numeric Telegram User ID:")
        return
    await state.update_data(chat_uid=int(message.text))
    await state.set_state(BotStates.admin_msg_text)
    await message.answer("📝 Write your message to send to this user:")

@dp.message(BotStates.admin_msg_text)
async def process_chat_txt(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    uid = data.get('chat_uid')
    try:
        await bot.send_message(uid, f"💬 <b>Message from Support:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer(f"✅ Message sent successfully to user <code>{uid}</code>.", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    except Exception as e:
        await message.answer(f"❌ Failed to send message. User might have blocked the bot.\nError: {str(e)}", reply_markup=admin_panel_keyboard())
    await state.clear()


# --- 📢 BROADCAST NOTICE ---
@dp.message(F.text == "📢 Broadcast Notice")
async def admin_bc_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_broadcast)
    await message.answer("📢 Enter your global notice text to broadcast to all users:")

@dp.message(BotStates.admin_broadcast)
async def process_bc_preview(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    bc_text = message.text
    await state.update_data(bc_text=bc_text)
    
    confirm_buttons = [
        [
            InlineKeyboardButton(text="✅ Send Notice", callback_data="bc_send_confirm"),
            InlineKeyboardButton(text="❌ Reject", callback_data="bc_send_reject")
        ]
    ]
    await message.answer(
        f"📝 <b>Broadcast Notice Preview:</b>\n\n"
        f"📢 {bc_text}\n\n"
        f"❓ আপনি কি নিশ্চিতভাবে এই নোটিশটি সকল ইউজারের কাছে পাঠাতে চান?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=confirm_buttons)
    )

@dp.callback_query(F.data == "bc_send_confirm")
async def handle_bc_execution(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    bc_text = data.get("bc_text")
    
    if not bc_text:
        await callback.answer("❌ নোটিশ খুঁজে পাওয়া যায়নি!", show_alert=True)
        await state.clear()
        return

    await callback.message.edit_text("⏳ Broadcasting message to database users, please wait...")
    
    async with get_db() as db:
        async with db.execute("SELECT user_id FROM users") as cursor: users = await cursor.fetchall()
        
    success = 0
    failed = 0
    
    async with get_db() as db:
        for u in users:
            try:
                msg = await bot.send_message(u[0], f"📢 <b>Notice:</b>\n\n{bc_text}", parse_mode="HTML")
                success += 1
                await db.execute("INSERT INTO broadcast_logs (user_id, message_id) VALUES (?, ?)", (u[0], msg.message_id))
                await asyncio.sleep(0.05) 
            except:
                failed += 1
        await db.commit()
            
    await callback.message.answer(f"✅ Broadcast Done!\n🟢 Success: <code>{success}</code>\n🔴 Failed/Blocked: <code>{failed}</code>\n📝 Records saved for future deletion.", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    await state.clear()

@dp.callback_query(F.data == "bc_send_reject")
async def handle_bc_rejection(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.clear()
    await callback.message.edit_text("❌ ব্রডকাস্ট নোটিশটি বাতিল করা হয়েছে।")


# --- 🗑️ DELETE BROADCASTS FROM ALL USERS ---
@dp.message(F.text == "🗑️ Delete Broadcasts")
async def delete_all_broadcasts(message: Message):
    if message.from_user.id != ADMIN_ID: return
    
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM broadcast_logs") as cursor:
            total = (await cursor.fetchone())[0]
            
    if total == 0:
        await message.answer("📋 ডিলিট করার মতো কোনো ব্রডকাস্ট মেসেজের রেকর্ড ডাটাবেজে নেই।")
        return
        
    buttons = [
        [
            InlineKeyboardButton(text="✅ Yes, Delete From Everyone", callback_data="confirm_delete_bc"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_delete_bc")
        ]
    ]
    await message.answer(
        f"⚠️ <b>সতর্কবার্তা!</b>\n\n"
        f"ডাটাবেজে মোট <code>{total}</code> টি সফলভাবে পাঠানো মেসেজের রেকর্ড আছে। "
        f"আপনি কি নিশ্চিতভাবে এই সব নোটিশ ইউজারদের ইনবক্স/চ্যাট থেকে সম্পূর্ণ ডিলিট করতে চান?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data == "confirm_delete_bc")
async def process_delete_bc(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    await callback.message.edit_text("⏳ ইউজারদের ইনবক্স থেকে মেসেজগুলো মুছে ফেলা হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
    
    async with get_db() as db:
        async with db.execute("SELECT user_id, message_id FROM broadcast_logs") as cursor:
            logs = await cursor.fetchall()
            
    deleted = 0
    failed = 0
    
    for user_id, message_id in logs:
        try:
            await bot.delete_message(chat_id=user_id, message_id=message_id)
            deleted += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04) 
        
    async with get_db() as db:
        await db.execute("DELETE FROM broadcast_logs")
        await db.commit()
        
    await callback.message.answer(
        f"✅ <b>মেসেজ ডিলিট সম্পন্ন!</b>\n\n"
        f"🟢 ইউজারদের চ্যাট থেকে মুছে গেছে: <code>{deleted}</code> টি\n"
        f"🔴 মোষা যায়নি: <code>{failed}</code> টি",
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard()
    )

@dp.callback_query(F.data == "cancel_delete_bc")
async def cancel_delete_bc(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("❌ ব্রডকাস্ট মেসেজ ডিলিট করার রিকোয়েস্ট বাতিল করা হয়েছে।")


# --- 🔍 CHECK USER BALANCE ---
@dp.message(F.text == "🔍 Check User Balance")
async def check_user_balance_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_check_user_id)
    await message.answer("🔍 তথ্য চেক করতে ইউজারের <b>Telegram User ID</b> দিন:", parse_mode="HTML")

@dp.message(BotStates.admin_check_user_id)
async def check_user_balance_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.isdigit():
        await message.answer("❌ ভুল আইডি। শুধুমাত্র সংখ্যার আইডিটি দিন:")
        return
    
    target_id = int(message.text)
    async with get_db() as db:
        async with db.execute("SELECT balance, status FROM users WHERE user_id = ?", (target_id,)) as cursor:
            user_data = await cursor.fetchone()
            
    if user_data:
        await message.answer(
            f"👤 <b>ইউজার প্রোফাইল তথ্য:</b>\n\n"
            f"🆔 <b>User ID:</b> <code>{target_id}</code>\n"
            f"💵 <b>Current Balance:</b> <code>{user_data[0]} Tk</code>\n"
            f"⚡ <b>Status:</b> <code>{user_data[1]}</code>",
            parse_mode="HTML",
            reply_markup=admin_panel_keyboard()
        )
    else:
        await message.answer("❌ এই আইডি সম্বলিত কোনো ইউজার ডাটাবেজে পাওয়া যায়নি!", reply_markup=admin_panel_keyboard())
    await state.clear()


# --- 💵 CREDIT BALANCE ---
@dp.message(F.text == "💵 Credit Balance")
async def admin_mod_bal_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.set_state(BotStates.admin_credit_id)
    await message.answer("🆔 Enter Telegram User ID to add balance:")

@dp.message(BotStates.admin_credit_id)
async def process_mod_bal_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.isdigit():
        await message.answer("❌ Invalid ID. Enter numbers only:")
        return
    await state.update_data(mod_uid=int(message.text))
    await state.set_state(BotStates.admin_credit_amt)
    await message.answer("💰 Enter Amount to add:")

@dp.message(BotStates.admin_credit_amt)
async def process_mod_bal_amt(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    clean_text = message.text.replace('.', '', 1).strip()
    if not clean_text.isdigit():
        await message.answer("❌ Enter valid amount:")
        return
    data = await state.get_data()
    uid = data.get('mod_uid')
    amt = float(message.text)
    
    async with get_db() as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))
        await db.commit()
    await message.answer(f"✅ Balance adjusted successfully for user <code>{uid}</code>.", parse_mode="HTML", reply_markup=admin_panel_keyboard())
    try: await bot.send_message(uid, f"💰 Admin added `+{amt} Tk` to your balance!")
    except: pass
    await state.clear()

# --- ADD MONEY MODULE ---
@dp.message(F.text == "💰 Add Money")
async def add_money_menu(message: Message):
    buttons = [
        [InlineKeyboardButton(text="bKash", callback_data="pay_bkash"), InlineKeyboardButton(text="Nagad", callback_data="pay_nagad")],
        [InlineKeyboardButton(text="Rocket", callback_data="pay_rocket"), InlineKeyboardButton(text="Binance", callback_data="pay_binance")]
    ]
    await message.answer("💰 <b>Select payment method:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("pay_"))
async def process_payment_method(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split("_")[1].upper()
    await state.update_data(payment_method=method)
    
    num = ""
    if method == "BKASH": num = BKASH_NUMBER
    elif method == "NAGAD": num = NAGAD
    elif method == "ROCKET": num = ROCKET_NUMBER
    elif method == "BINANCE": num = BINANCE_ID
        
    instructions = (
        f"💵 <b>Method:</b> {method}\n"
        f"💳 <b>Number/ID:</b> <code>{num}</code>\n\n"
        f"💬 Send money first, then reply here with your <b>Screenshot</b> or <b>Transaction ID (TrxID)</b>:"
    )
    await callback.message.edit_text(instructions, parse_mode="HTML")
    await state.set_state(BotStates.submit_payment_proof)

@dp.message(BotStates.submit_payment_proof)
async def receive_payment_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    method = data.get("payment_method")
    user_id = message.from_user.id
    
    admin_buttons = [[InlineKeyboardButton(text="✅ Approve", callback_data=f"dep_app_{user_id}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"dep_rej_{user_id}")]]
    caption = f"💰 <b>Deposit Request</b>\n👤 ID: <code>{user_id}</code>\n💵 Method: {method}\nProof: "
    
    try:
        if message.photo:
            msg = await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=admin_buttons))
        else:
            msg = await bot.send_message(ADMIN_ID, caption + f"\n<code>{message.text}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=admin_buttons))
        
        active_deposits[msg.message_id] = {"user_id": user_id, "status": "pending"}
        await message.answer("✅ আপনার ডিপোজিট রিকোয়েস্টটি সফলভাবে অ্যাডমিনের কাছে পাঠানো হয়েছে। ভেরিফিকেশনের জন্য অনুগ্রহ করে কিছু সময় অপেক্ষা করুন।")
    except Exception as e:
        await message.answer(f"❌ Failed to submit proof. Error: {str(e)}")
        
    await state.clear()

@dp.callback_query(F.data.startswith("dep_"))
async def handle_deposit_decision(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    _, action, target_id = callback.data.split("_")
    target_id = int(target_id)
    msg_id = callback.message.message_id
    
    if action == "app":
        active_deposits[msg_id] = {"user_id": target_id, "status": "processing"} 
        await state.update_data(dep_user=target_id, dep_msg_id=msg_id)
        await callback.message.answer(f"✍️ Enter the Amount to add for user <code>{target_id}</code>:", parse_mode="HTML")
        await state.set_state(BotStates.deposit_load_amt)
        await callback.answer()
    else:
        if msg_id in active_deposits: active_deposits[msg_id]["status"] = "rejected"
        try:
            if callback.message.photo: await callback.message.edit_caption(caption="❌ Deposit Request Denied & Rejected.")
            else: await callback.message.edit_text("❌ Deposit Request Denied & Rejected.")
        except: pass
        try: await bot.send_message(target_id, "❌ আপনার ডিপোজিট রিকোয়েস্টটি অ্যাডমিন রিজেক্ট করে দিয়েছেন।")
        except: pass
        await callback.answer("Rejected successfully.")

@dp.message(BotStates.deposit_load_amt)
async def process_deposit_load_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    clean_text = message.text.replace('.', '', 1).strip()
    if not clean_text.isdigit(): 
        await message.answer("❌ Invalid number format. Enter balance amount:")
        return
        
    sdata = await state.get_data()
    target = sdata['dep_user']
    msg_id = sdata['dep_msg_id']
    amt = float(message.text)
    
    try:
        async with get_db() as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (target, amt))
            await db.commit()
            
        if msg_id in active_deposits: active_deposits[msg_id]["status"] = "approved"
        await message.answer(f"✅ Successfully Loaded {amt} Tk to user <code>{target}</code>.", parse_mode="HTML", reply_markup=admin_panel_keyboard())
        try: await bot.send_message(target, f"🎉 Approved! `+{amt} Tk` added to your balance.")
        except: pass
    except Exception as e:
        await message.answer(f"❌ Error occurred: {str(e)}", reply_markup=admin_panel_keyboard())
        
    await state.clear()


# --- 📋 PENDING ORDERS ---
@dp.message(F.text == "📋 Pending Orders")
async def pending_orders_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        async with get_db() as db:
            async with db.execute("SELECT id,user_id,username,product,price,order_time,plan_id FROM pending_orders ORDER BY id DESC") as cursor:
                rows = await cursor.fetchall()
        if not rows:
            await message.answer("📋 No pending orders.")
            return
        for r in rows:
            kb=[[InlineKeyboardButton(text="✅ Approve", callback_data=f"pend_app_{r[0]}"),InlineKeyboardButton(text="❌ Reject", callback_data=f"pend_rej_{r[0]}")]]
            
            safe_username = str(r[2]).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[') if r[2] else 'N/A'
            safe_product = str(r[3]).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
            
            await message.answer(
                f"👤 <b>User ID:</b> <code>{r[1]}</code>\n"
                f"📛 <b>Username:</b> @{safe_username}\n"
                f"📦 <b>Product:</b> {safe_product}\n"
                f"💰 <b>Price:</b> {r[4]} Tk\n"
                f"⏰ <b>Time:</b> {r[5]}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )
    except Exception as e:
        await message.answer(f"❌ Error fetching pending orders: {str(e)}")


# --- USER PANEL SHOP ---
@dp.message(F.text == "🛒 Panel Shop")
async def show_products(message: Message):
    async with get_db() as db:
        async with db.execute("SELECT product_name FROM main_products") as cursor: products = await cursor.fetchall()
    if not products:
        await message.answer("🛒 Empty shop.")
        return
    buttons = [[InlineKeyboardButton(text=prod[0], callback_data=f"prod_{prod[0]}")] for prod in products]
    await message.answer("🛒 <b>Select Product:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("prod_"))
async def show_plans(callback: CallbackQuery):
    prod_name = callback.data.split("_")[1]
    async with get_db() as db:
        async with db.execute("SELECT id, duration, price FROM plans WHERE product_name = ?", (prod_name,)) as cursor: plans = await cursor.fetchall()
    if not plans:
        await callback.answer("❌ No plans under this category.", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(text=f"⏱️ {plan[1]} - {plan[2]} Tk", callback_data=f"plan_{plan[0]}")] for plan in plans]
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="shop_main")])
    await callback.message.edit_text(f"📦 Choose Plan:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "shop_main")
async def back_to_shop_main(callback: CallbackQuery):
    async with get_db() as db:
        async with db.execute("SELECT product_name FROM main_products") as cursor: products = await cursor.fetchall()
    buttons = [[InlineKeyboardButton(text=p[0], callback_data=f"prod_{p[0]}")] for p in products]
    await callback.message.edit_text("🛒 <b>Select Product:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("plan_"))
async def confirm_purchase(callback: CallbackQuery):
    plan_id = int(callback.data.split("_")[1])
    async with get_db() as db:
        async with db.execute("SELECT product_name, duration, price FROM plans WHERE id = ?", (plan_id,)) as cursor: plan = await cursor.fetchone()
    buttons = [[InlineKeyboardButton(text="🛒 Buy Now", callback_data=f"buy_{plan_id}"), InlineKeyboardButton(text="⬅️ Back", callback_data=f"prod_{plan[0]}")]]
    await callback.message.edit_text(f"📊 <b>Order Confirmation</b>\n📦 {plan[0]} ({plan[1]})\n💵 Price: {plan[2]} Tk\n\nProceed?", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# 📌 অর্ডার সেভ এবং নোটিফিকেশন মডিউল
@dp.callback_query(F.data.startswith("buy_"))
async def process_buy_request(callback: CallbackQuery):
    plan_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    username = callback.from_user.username or "N/A"
    
    async with get_db() as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor: balance = (await cursor.fetchone())[0]
        async with db.execute("SELECT product_name, duration, price FROM plans WHERE id = ?", (plan_id,)) as cursor: plan = await cursor.fetchone()
    
    if balance < plan[2]:
        await callback.answer("❌ Insufficient Balance!", show_alert=True)
        return
        
    order_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    product_details = f"{plan[0]} ({plan[1]})"
    
    async with get_db() as db:
        await db.execute("INSERT INTO pending_orders (user_id,username,product,price,order_time,plan_id) VALUES (?,?,?,?,?,?)",
                         (user_id, username, product_details, plan[2], order_time, plan_id))
        await db.commit()
        
    await callback.message.edit_text("⏳ Order saved and sent to Pending Orders.")
    
    # ইউজারনেমের আন্ডারস্কোর ফিক্স করে সাধারণ স্ট্রিং আকারে নেওয়া (ব্যাকস্ল্যাশ এরর এড়াতে)
    clean_username = username.replace('_', ' ')
    
    # 🔔 অ্যাডমিনের কাছে ইনস্ট্যান্ট নোটিফিকেশন অ্যালার্ট পাঠানো
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🛒 <b>নতুন পেন্ডিং অর্ডার নোটিফিকেশন!</b>\n\n"
                 f"👤 <b>ইউজার আইডি:</b> <code>{user_id}</code>\n"
                 f"📛 <b>ইউজারনেম:</b> @{clean_username}\n"
                 f"📦 <b>প্রোডাক্ট:</b> <code>{product_details}</code>\n"
                 f"💰 <b>মূল্য:</b> <code>{plan[2]} Tk</code>\n"
                 f"⏰ <b>সময়:</b> {order_time}\n\n"
                 f"💡 চেক করতে অ্যাডমিন প্যানেলের <b>📋 Pending Orders</b> বাটনে ক্লিক করুন।",
            parse_mode="HTML"
        )
    except Exception:
        pass


@dp.callback_query(F.data.startswith("pend_"))
async def pending_decision(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    _, action, oid = callback.data.split("_")
    oid=int(oid)
    async with get_db() as db:
        async with db.execute("SELECT user_id,plan_id FROM pending_orders WHERE id=?", (oid,)) as c:
            row=await c.fetchone()
        if not row:
            await callback.answer("Order not found", show_alert=True); return
        if action=="rej":
            await db.execute("DELETE FROM pending_orders WHERE id=?", (oid,))
            await db.commit()
            await callback.message.edit_text("❌ Order Rejected & Removed.")
            return
        user_id, plan_id=row
        async with db.execute("SELECT product_name,duration,price FROM plans WHERE id=?", (plan_id,)) as c:
            plan=await c.fetchone()
        
        await state.update_data(key_uid=user_id, key_pid=plan_id, key_pname=plan[0], key_dur=plan[1], key_prc=plan[2], key_oid=oid)
        await callback.message.answer(f"✍️ Paste the <b>License Key</b> for user <code>{user_id}</code>:", parse_mode="HTML")
        await state.set_state(BotStates.input_license_key)
        await callback.answer()


@dp.message(BotStates.input_license_key)
async def deliver_key_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    user_id, price, pname, duration = data['key_uid'], data['key_prc'], data['key_pname'], data['key_dur']
    oid = data.get('key_oid')
    license_key = message.text
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        async with get_db() as db:
            async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
                current_bal_row = await cursor.fetchone()
                
            if not current_bal_row or current_bal_row[0] < price:
                await message.answer(f"❌ Delivery Failed! User <code>{user_id}</code> has insufficient balance now.", parse_mode="HTML")
                if oid:
                    await db.execute("DELETE FROM pending_orders WHERE id=?", (oid,))
                    await db.commit()
                await state.clear()
                return
                
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
            
            await db.execute(
                "INSERT INTO delivered_keys (user_id, product_name, license_key, delivery_time) VALUES (?, ?, ?, ?)",
                (user_id, f"{pname} ({duration})", license_key, current_time)
            )
            
            if oid:
                await db.execute("DELETE FROM pending_orders WHERE id=?", (oid,))
            await db.commit()
            
        await message.answer("✅ Key delivered successfully and logged to user history.", reply_markup=admin_panel_keyboard())
        try: await bot.send_message(user_id, f"🎉 <b>Your Order is Approved!</b>\n\n📦 <b>Product:</b> {pname} ({duration})\n🔑 <b>Key:</b> <code>{license_key}</code>\n\n💡 This key is now saved in your 🔑 <b>My Keys</b> menu.", parse_mode="HTML")
        except: pass
    except Exception as e:
        await message.answer(f"❌ Error during order delivery: {str(e)}", reply_markup=admin_panel_keyboard())
        
    await state.clear()

# --- 🔑 MY KEYS MODULE ---
@dp.message(F.text == "🔑 My Keys")
async def user_keys_history(message: Message):
    user_id = message.from_user.id
    async with get_db() as db:
        async with db.execute(
            "SELECT product_name, license_key, delivery_time FROM delivered_keys WHERE user_id = ? ORDER BY id DESC", 
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await message.answer("🔑 আপনার কেনা কোনো লাইসেন্স কী এর রেকর্ড পাওয়া যায়নি।")
        return
        
    history_text = "🔑 <b>Your Purchased Keys History:</b>\n\n"
    for idx, r in enumerate(rows, 1):
        history_text += (
            f"{idx}. 📦 <b>Product:</b> {r[0]}\n"
            f"   🔑 <b>Key:</b> <code>{r[1]}</code>\n"
            f"   ⏰ <b>Date:</b> {r[2]}\n"
            f"----------------------------------\n"
        )
    await message.answer(history_text, parse_mode="HTML")


# --- OTHER STANDARD MODULES ---
@dp.message(F.text == "👤 Balance Check")
async def balance_check(message: Message):
    async with get_db() as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,)) as cursor: balance = (await cursor.fetchone())[0]
    await message.answer(f"👤 <b>Your Balance:</b> {balance} Tk", parse_mode="HTML")

@dp.message(F.text == "📞 Support")
async def support_handler(message: Message):
    await message.answer("📞 Contact Owner/Support: @FlassySupport_bot")

@dp.callback_query(F.data == "adm_newprod")
async def adm_cat_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Enter new product category name:")
    await state.set_state(BotStates.create_product_main)

@dp.message(BotStates.create_product_main)
async def fsm_pmain(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    async with get_db() as db:
        try:
            await db.execute("INSERT INTO main_products (product_name) VALUES (?)", (message.text,))
            await db.commit()
            await message.answer(f"✅ Category <code>{message.text}</code> created.", parse_mode="HTML")
        except: 
            await message.answer("❌ Error/Duplicate Category.")
    await state.clear()

@dp.callback_query(F.data == "adm_addplan")
async def adm_plan_start(callback: CallbackQuery):
    async with get_db() as db:
        async with db.execute("SELECT product_name FROM main_products") as cursor: prods = await cursor.fetchall()
    buttons = [[InlineKeyboardButton(text=p[0], callback_data=f"ap_sel_{p[0]}")] for p in prods]
    await callback.message.edit_text("🎯 Select a category:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("ap_sel_"))
async def adm_plan_selected(callback: CallbackQuery, state: FSMContext):
    pn = callback.data.split("_")[2]
    await state.update_data(selected_main_product=pn)
    await callback.message.answer("⏱️ Enter plan validity/name (e.g., `30 Days`):")
    await state.set_state(BotStates.add_plan_duration)

@dp.message(BotStates.add_plan_duration)
async def fsm_pdur(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.update_data(plan_dur=message.text)
    await message.answer("💵 Enter Price:")
    await state.set_state(BotStates.add_plan_price)

@dp.message(BotStates.add_plan_price)
async def fsm_pprc(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    if not message.text.replace('.', '', 1).isdigit(): return
    data = await state.get_data()
    async with get_db() as db:
        await db.execute("INSERT INTO plans (product_name, duration, price) VALUES (?, ?, ?)", (data['selected_main_product'], data['plan_dur'], float(message.text)))
        await db.commit()
    await message.answer("✅ Plan added successfully.")
    await state.clear()

@dp.callback_query(F.data.startswith("dcat_"))
async def delete_category_complete(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    cid = int(callback.data.split("_")[1])
    async with get_db() as db:
        async with db.execute("SELECT product_name FROM main_products WHERE id = ?", (cid,)) as cursor: row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM main_products WHERE id = ?", (cid,))
            await db.execute("DELETE FROM plans WHERE product_name = ?", (row[0],))
            await db.commit()
    await callback.message.edit_text("🗑️ Category and its plans deleted.")

@dp.callback_query(F.data.startswith("dplan_"))
async def delete_single_plan(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    pid = int(callback.data.split("_")[1])
    async with get_db() as db:
        await db.execute("DELETE FROM plans WHERE id = ?", (pid,))
        await db.commit()
    await callback.message.edit_text("🗑️ Plan deleted.")


@dp.callback_query(F.data == "check_join")
async def check_join_callback(callback: CallbackQuery):
    user_id = callback.from_user.id

    joined = await is_user_joined(user_id)

    if not joined:
        await callback.answer("❌ You have not joined all channels yet.", show_alert=True)
        return

    await callback.message.delete()
    await callback.message.answer(
        "✅ Verification successful!\n\nWelcome!",
        reply_markup=main_menu_keyboard(user_id)
    )


async def set_bot_menu(bot: Bot):
    await bot.set_my_commands([BotCommand(command="start", description="Restart Again 🔄")])

# --- MAIN RUNNER ---
async def main():
    try:
        await init_db()
        await set_bot_menu(bot)
        print("Pure Async Anti-Spam Activated. Notification modules online!")
        await dp.start_polling(bot)
    finally:
        global db_connection
        if db_connection:
            db_connection.close()

if __name__ == "__main__":
    asyncio.run(main())