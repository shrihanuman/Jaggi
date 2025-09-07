import logging
import asyncio
import sqlite3
import random
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from telegram.error import BadRequest, TelegramError
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
from telethon import events
import aiosqlite
import phonenumbers
from typing import Dict, Any, List, Tuple
import json

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
PHONE, OTP, FORWARD_SOURCE, FORWARD_TARGET, FORWARD_REPLACEMENTS = range(5)

class EnhancedAutoForwardBot:
    def __init__(self, bot_token: str, owner_id: int, api_id: int, api_hash: str, sms_service=None):
        self.bot_token = bot_token
        self.owner_id = owner_id
        self.api_id = api_id
        self.api_hash = api_hash
        self.sms_service = sms_service
        self.application = Application.builder().token(bot_token).build()
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        self.user_clients: Dict[int, TelegramClient] = {}
        self.forwarding_tasks: Dict[int, asyncio.Task] = {}
        
        # Setup handlers
        self.setup_handlers()
        
    def setup_handlers(self):
        """Setup all message handlers"""
        # Conversation handler for setup process
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start), CommandHandler('setup', self.setup)],
            states={
                PHONE: [MessageHandler(filters.CONTACT, self.handle_contact)],
                OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.verify_otp)],
                FORWARD_SOURCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_forward_source)],
                FORWARD_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_forward_target)],
                FORWARD_REPLACEMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_forward_replacements)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("add_forward", self.add_forward))
        self.application.add_handler(CommandHandler("list_rules", self.list_rules))
        self.application.add_handler(CommandHandler("stop_forward", self.stop_forward))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast, filters.User(user_id=self.owner_id)))
        self.application.add_handler(CommandHandler("stats", self.stats, filters.User(user_id=self.owner_id)))
        self.application.add_handler(CommandHandler("user_stats", self.user_stats, filters.User(user_id=self.owner_id)))
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
    async def init_db(self):
        """Initialize database connection with enhanced schema"""
        self.db = await aiosqlite.connect('forward_bot.db', isolation_level=None)
        
        # Enable WAL mode for better concurrency
        await self.db.execute('PRAGMA journal_mode=WAL')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone TEXT UNIQUE,
                session_string TEXT,
                is_verified BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS otps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT,
                otp_code TEXT,
                expires_at DATETIME,
                is_used BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS forwarding_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                source_channel TEXT,
                target_channel TEXT,
                replacement_rules TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_forwarded DATETIME,
                FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
            )
        ''')
        
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS forwarded_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER,
                message_id INTEGER,
                forwarded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (rule_id) REFERENCES forwarding_rules (id) ON DELETE CASCADE
            )
        ''')
        
        await self.db.execute('''
            CREATE INDEX IF NOT EXISTS idx_users_verified ON users(is_verified)
        ''')
        
        await self.db.execute('''
            CREATE INDEX IF NOT EXISTS idx_rules_active ON forwarding_rules(is_active)
        ''')
        
        await self.db.execute('''
            CREATE INDEX IF NOT EXISTS idx_rules_user ON forwarding_rules(user_id)
        ''')
        
        await self.db.commit()
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Send welcome message and start setup process"""
        user_id = update.effective_user.id
        
        # Update user last active time
        await self.db.execute(
            "INSERT OR REPLACE INTO users (user_id, last_active) VALUES (?, CURRENT_TIMESTAMP)",
            (user_id,)
        )
        await self.db.commit()
        
        welcome_text = """
🤖 **Enhanced Auto Forward Bot** 🤖

I can help you automatically forward messages from any source channel to your target channel with advanced features.

**Features:**
- 🔄 Auto-forwarding from any source to your channel
- 🔧 Text and link replacement
- 🔒 Secure OTP authentication
- ⚡ Easy setup
- 📊 Message tracking and statistics

**Commands:**
/setup - Verify your account and get started
/add_forward - Add a new forwarding rule
/list_rules - List your forwarding rules
/stop_forward - Stop a forwarding rule
/help - Show this help message

To get started, use /setup to verify your account.
        """
        
        await update.message.reply_text(welcome_text)
        
        # Check if user is already verified
        async with self.db.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
        if user and user[0]:
            await update.message.reply_text(
                "Your account is already verified! Use /add_forward to set up forwarding rules."
            )
            return ConversationHandler.END
        
        # Request phone number
        keyboard = [[InlineKeyboardButton("📱 Share Phone Number", request_contact=True)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "To verify your account, please share your phone number:",
            reply_markup=reply_markup
        )
        
        # Initialize user session
        self.user_sessions[user_id] = {"step": PHONE}
        
        return PHONE
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message"""
        help_text = """
🤖 **Enhanced Auto Forward Bot - Help** 🤖

**Available Commands:**
/setup - Verify your account with OTP
/add_forward - Set up a new forwarding rule
/list_rules - View your current forwarding rules
/stop_forward [id] - Stop a specific forwarding rule
/help - Show this help message

**How to set up forwarding:**
1. Use /setup to verify your account with OTP
2. Use /add_forward to create a forwarding rule
3. Provide source channel (where to forward from)
4. Provide target channel (where to forward to)
5. Optionally add text replacement rules

**Replacement Rules Format:**
`original_text->replacement_text, another_text->another_replacement`

**Example:**
`telegram->signal, example.com->mysite.com`

Need assistance? Contact the bot administrator.
        """
        await update.message.reply_text(help_text)
    
    async def setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Start setup process directly"""
        return await self.start(update, context)
    
    async def handle_contact(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle contact sharing with validation"""
        user_id = update.effective_user.id
        phone_number = update.message.contact.phone_number
        
        # Validate and format phone number
        try:
            parsed_number = phonenumbers.parse(phone_number, None)
            if not phonenumbers.is_valid_number(parsed_number):
                await update.message.reply_text("❌ Invalid phone number. Please share a valid phone number.")
                return PHONE
                
            formatted_number = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
        except Exception as e:
            logger.error(f"Phone number parsing error: {e}")
            await update.message.reply_text("❌ Invalid phone number format. Please try again.")
            return PHONE
        
        # Check if this phone number is already registered with another account
        async with self.db.execute("SELECT user_id FROM users WHERE phone = ? AND user_id != ?", 
                                  (formatted_number, user_id)) as cursor:
            existing_user = await cursor.fetchone()
            
        if existing_user:
            await update.message.reply_text(
                "❌ This phone number is already registered with another account. "
                "Please use a different phone number or contact support."
            )
            return PHONE
        
        # Store phone number in database
        await self.db.execute(
            "INSERT OR REPLACE INTO users (user_id, phone, last_active) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id, formatted_number)
        )
        await self.db.commit()
        
        # Generate OTP
        otp = str(random.randint(100000, 999999))
        expires_at = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Store OTP in database
        await self.db.execute(
            "INSERT INTO otps (user_id, phone, otp_code, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, formatted_number, otp, expires_at)
        )
        await self.db.commit()
        
        # Send OTP via SMS (if service available) or via message
        if self.sms_service:
            try:
                await self.sms_service.send_sms(formatted_number, f"Your verification code is: {otp}")
                await update.message.reply_text(
                    f"✅ OTP sent to {formatted_number}. Please enter the code within 10 minutes."
                )
            except Exception as e:
                logger.error(f"SMS sending failed: {e}")
                await update.message.reply_text(
                    f"❌ Failed to send SMS. Your OTP is: {otp}. Please enter this code."
                )
        else:
            await update.message.reply_text(
                f"📋 Your OTP is: {otp}. Please enter this code within 10 minutes."
            )
        
        # Update user session
        self.user_sessions[user_id] = {
            "step": OTP,
            "phone": formatted_number
        }
        
        return OTP
    
    async def verify_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Verify OTP code and create user session"""
        user_id = update.effective_user.id
        otp_code = update.message.text.strip()
        
        if user_id not in self.user_sessions or self.user_sessions[user_id].get("step") != OTP:
            await update.message.reply_text("❌ Please start the verification process with /setup")
            return ConversationHandler.END
        
        # Verify OTP
        async with self.db.execute(
            "SELECT otp_code, expires_at FROM otps WHERE user_id = ? AND is_used = 0 ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            otp_data = await cursor.fetchone()
        
        if not otp_data:
            await update.message.reply_text("❌ No OTP found. Please start over with /setup")
            return ConversationHandler.END
        
        stored_otp, expires_at = otp_data
        
        if datetime.now() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S"):
            await update.message.reply_text("❌ OTP has expired. Please request a new one with /setup")
            return ConversationHandler.END
        
        if otp_code == stored_otp:
            # Mark OTP as used and verify user
            await self.db.execute(
                "UPDATE otps SET is_used = 1 WHERE user_id = ? AND otp_code = ?",
                (user_id, otp_code)
            )
            await self.db.execute(
                "UPDATE users SET is_verified = 1, last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                (user_id,)
            )
            await self.db.commit()
            
            # Create Telethon client for user
            client = TelegramClient(StringSession(), self.api_id, self.api_hash)
            
            try:
                # Connect and authenticate with user's phone number
                await client.connect()
                
                # Send code request
                sent = await client.send_code_request(self.user_sessions[user_id]["phone"])
                
                # Sign in with the code
                await client.sign_in(self.user_sessions[user_id]["phone"], otp_code)
                
                # Save session string
                session_string = client.session.save()
                await self.db.execute(
                    "UPDATE users SET session_string = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (session_string, user_id)
                )
                await self.db.commit()
                
                # Store client for later use
                self.user_clients[user_id] = client
                
                await update.message.reply_text(
                    "✅ Account verified successfully!\n\n"
                    "Now you can set up auto-forwarding using /add_forward command."
                )
                
            except Exception as e:
                logger.error(f"Error creating user session: {e}")
                await update.message.reply_text(
                    "❌ Error verifying your account. Please try again with /setup."
                )
                return OTP
            
            # Clear user session
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
                
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Invalid OTP. Please try again.")
            return OTP
    
    async def add_forward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add a new forwarding rule"""
        user_id = update.effective_user.id
        
        # Update last active time
        await self.db.execute(
            "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        await self.db.commit()
        
        # Check if user is verified
        async with self.db.execute("SELECT is_verified, session_string FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
        if not user or not user[0]:
            await update.message.reply_text("❌ Please verify your account first using /setup")
            return
        
        # Check if we have a valid session
        if user_id not in self.user_clients or not self.user_clients[user_id].is_connected():
            try:
                # Recreate client from session string
                session_string = user[1]
                if not session_string:
                    await update.message.reply_text("❌ Session expired. Please verify again with /setup.")
                    return
                    
                client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
                await client.connect()
                
                # Test the connection
                await client.get_me()
                
                self.user_clients[user_id] = client
            except Exception as e:
                logger.error(f"Error reconnecting user session: {e}")
                await update.message.reply_text(
                    "❌ Error accessing your account. Please verify again with /setup."
                )
                return
        
        # Check if user has reached maximum forwarding rules (prevent abuse)
        async with self.db.execute(
            "SELECT COUNT(*) FROM forwarding_rules WHERE user_id = ? AND is_active = 1", 
            (user_id,)
        ) as cursor:
            rule_count = (await cursor.fetchone())[0]
            
        if rule_count >= 10:  # Limit to 10 active rules per user
            await update.message.reply_text(
                "❌ You have reached the maximum number of active forwarding rules (10). "
                "Please stop some rules with /stop_forward before adding new ones."
            )
            return
        
        # Initialize forwarding setup in user session
        self.user_sessions[user_id] = {
            "step": FORWARD_SOURCE,
            "forwarding_rule": {}
        }
        
        await update.message.reply_text(
            "Please provide the source channel username or ID (e.g., @sourcechannel or -1001234567890):\n\n"
            "💡 Make sure you have joined this channel and have reading permissions."
        )
    
    async def handle_forward_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle source channel input with validation"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions or self.user_sessions[user_id].get("step") != FORWARD_SOURCE:
            await update.message.reply_text("❌ Please start over with /add_forward")
            return ConversationHandler.END
        
        source_channel = update.message.text.strip()
        
        # Validate that user has access to source channel
        try:
            client = self.user_clients[user_id]
            entity = await client.get_entity(source_channel)
            
            # Check if user has permission to read from this channel
            try:
                messages = await client.get_messages(entity, limit=1)
                if not messages:
                    await update.message.reply_text(
                        "❌ You don't have access to this channel or it's empty. "
                        "Please make sure you've joined the channel and have reading permissions."
                    )
                    return FORWARD_SOURCE
                    
                # Store entity info for later use
                self.user_sessions[user_id]["source_entity"] = entity
                    
            except Exception as e:
                logger.error(f"Error accessing source channel: {e}")
                await update.message.reply_text(
                    "❌ You don't have access to this channel. "
                    "Please make sure you've joined the channel and have reading permissions."
                )
                return FORWARD_SOURCE
                
        except ValueError:
            # Might be a private channel invite link
            if source_channel.startswith('https://t.me/+'):
                await update.message.reply_text(
                    "❌ Please provide the channel username or ID, not the invite link. "
                    "You need to join the channel first."
                )
                return FORWARD_SOURCE
            else:
                await update.message.reply_text(
                    "❌ Invalid channel format. Please provide a valid channel username or ID."
                )
                return FORWARD_SOURCE
        except Exception as e:
            logger.error(f"Error validating source channel: {e}")
            await update.message.reply_text(
                "❌ Invalid channel or you don't have access to it. "
                "Please provide a valid channel username or ID that you have access to."
            )
            return FORWARD_SOURCE
        
        self.user_sessions[user_id]["forwarding_rule"]["source"] = source_channel
        self.user_sessions[user_id]["step"] = FORWARD_TARGET
        
        await update.message.reply_text(
            "Now please provide the target channel username or ID (e.g., @targetchannel or -1001234567890):\n\n"
            "💡 Make sure you are an admin in this channel with posting permissions."
        )
        
        return FORWARD_TARGET
    
    async def handle_forward_target(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle target channel input with validation"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions or self.user_sessions[user_id].get("step") != FORWARD_TARGET:
            await update.message.reply_text("❌ Please start over with /add_forward")
            return ConversationHandler.END
        
        target_channel = update.message.text.strip()
        
        # Validate that user has admin access to target channel
        try:
            client = self.user_clients[user_id]
            entity = await client.get_entity(target_channel)
            
            # Check if user has permission to send messages to this channel
            try:
                # Try sending a test message (will be deleted immediately)
                message = await client.send_message(entity, "🔒 Testing permissions... (this message will be deleted)")
                await asyncio.sleep(1)  # Short delay
                await client.delete_messages(entity, message)
            except Exception as e:
                logger.error(f"Error testing target channel permissions: {e}")
                await update.message.reply_text(
                    "❌ You don't have admin permissions in this channel. "
                    "Please make sure you're an admin with posting permissions."
                )
                return FORWARD_TARGET
                
            # Store entity info for later use
            self.user_sessions[user_id]["target_entity"] = entity
                
        except Exception as e:
            logger.error(f"Error validating target channel: {e}")
            await update.message.reply_text(
                "❌ Invalid channel or you don't have admin permissions. "
                "Please provide a valid channel username or ID where you have admin rights."
            )
            return FORWARD_TARGET
        
        self.user_sessions[user_id]["forwarding_rule"]["target"] = target_channel
        self.user_sessions[user_id]["step"] = FORWARD_REPLACEMENTS
        
        await update.message.reply_text(
            "Optional: Provide text replacement rules in the format 'old->new' separated by commas.\n"
            "Example: 'telegram->signal, example.com->mysite.com'\n\n"
            "Or type 'skip' to continue without replacements:"
        )
        
        return FORWARD_REPLACEMENTS
    
    async def handle_forward_replacements(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle replacement rules input and start forwarding"""
        user_id = update.effective_user.id
        
        if user_id not in self.user_sessions or self.user_sessions[user_id].get("step") != FORWARD_REPLACEMENTS:
            await update.message.reply_text("❌ Please start over with /add_forward")
            return ConversationHandler.END
        
        replacements_text = update.message.text.strip()
        forwarding_rule = self.user_sessions[user_id]["forwarding_rule"]
        
        # Save to database
        replacement_rules = None if replacements_text.lower() == 'skip' else replacements_text
        
        # Insert the rule and get the rule ID
        cursor = await self.db.execute(
            "INSERT INTO forwarding_rules (user_id, source_channel, target_channel, replacement_rules) VALUES (?, ?, ?, ?)",
            (user_id, forwarding_rule["source"], forwarding_rule["target"], replacement_rules)
        )
        await self.db.commit()
        
        rule_id = cursor.lastrowid
        
        # Start forwarding messages
        if user_id in self.forwarding_tasks:
            self.forwarding_tasks[user_id].cancel()
            
        self.forwarding_tasks[user_id] = asyncio.create_task(
            self.start_forwarding(user_id, rule_id, forwarding_rule["source"], 
                                 forwarding_rule["target"], replacement_rules)
        )
        
        # Clear user session
        del self.user_sessions[user_id]
        
        await update.message.reply_text(
            f"✅ Forwarding rule added successfully!\n\n"
            f"📥 From: {forwarding_rule['source']}\n"
            f"📤 To: {forwarding_rule['target']}\n"
            f"🔧 Replacements: {replacement_rules or 'None'}\n\n"
            f"Auto-forwarding is now active. Use /list_rules to see all your rules."
        )
        
        return ConversationHandler.END
    
    async def start_forwarding(self, user_id: int, rule_id: int, source_channel: str, 
                              target_channel: str, replacement_rules: str):
        """Start forwarding messages from source to target channel"""
        try:
            client = self.user_clients[user_id]
            
            # Parse replacement rules
            replacements = []
            if replacement_rules:
                for rule in replacement_rules.split(','):
                    if '->' in rule:
                        old, new = rule.split('->', 1)
                        replacements.append((old.strip(), new.strip()))
            
            # Get the last message ID to start from
            async with self.db.execute(
                "SELECT message_id FROM forwarded_messages WHERE rule_id = ? ORDER BY id DESC LIMIT 1",
                (rule_id,)
            ) as cursor:
                last_message = await cursor.fetchone()
                
            last_id = last_message[0] if last_message else 0
            
            @client.on(events.NewMessage(chats=source_channel))
            async def handler(event):
                try:
                    # Skip old messages
                    if event.message.id <= last_id:
                        return
                    
                    message = event.message
                    text = message.text or message.caption or ""
                    
                    # Apply text replacements
                    for old, new in replacements:
                        text = text.replace(old, new)
                    
                    # Forward the message with replacements
                    if message.media:
                        # Handle media messages
                        if text:
                            sent_message = await client.send_file(target_channel, message.media, caption=text)
                        else:
                            sent_message = await client.send_file(target_channel, message.media)
                    else:
                        # Handle text messages
                        sent_message = await client.send_message(target_channel, text)
                    
                    # Record the forwarded message
                    await self.db.execute(
                        "INSERT INTO forwarded_messages (rule_id, message_id) VALUES (?, ?)",
                        (rule_id, event.message.id)
                    )
                    
                    # Update last forwarded time
                    await self.db.execute(
                        "UPDATE forwarding_rules SET last_forwarded = CURRENT_TIMESTAMP WHERE id = ?",
                        (rule_id,)
                    )
                    
                    await self.db.commit()
                    
                    logger.info(f"Forwarded message {event.message.id} from {source_channel} to {target_channel}")
                    
                except Exception as e:
                    logger.error(f"Error forwarding message: {e}")
            
            # Run the client
            await client.run_until_disconnected()
            
        except Exception as e:
            logger.error(f"Error in forwarding task for user {user_id}: {e}")
            # Try to reconnect
            await asyncio.sleep(5)
            self.forwarding_tasks[user_id] = asyncio.create_task(
                self.start_forwarding(user_id, rule_id, source_channel, target_channel, replacement_rules)
            )
    
    async def list_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List all forwarding rules for the user with enhanced information"""
        user_id = update.effective_user.id
        
        # Update last active time
        await self.db.execute(
            "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        await self.db.commit()
        
        # Check if user is verified
        async with self.db.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
        if not user or not user[0]:
            await update.message.reply_text("❌ Please verify your account first using /setup")
            return
        
        async with self.db.execute(
            """SELECT id, source_channel, target_channel, replacement_rules, is_active, 
                      created_at, last_forwarded 
               FROM forwarding_rules WHERE user_id = ? ORDER BY id DESC""",
            (user_id,)
        ) as cursor:
            rules = await cursor.fetchall()
        
        if not rules:
            await update.message.reply_text("You don't have any forwarding rules set up yet. Use /add_forward to create one.")
            return
        
        rules_text = "📋 Your Forwarding Rules:\n\n"
        for rule_id, source, target, replacements, is_active, created_at, last_forwarded in rules:
            status = "✅ Active" if is_active else "❌ Inactive"
            rules_text += f"🆔 Rule #{rule_id}: {source} → {target} ({status})\n"
            
            if replacements:
                rules_text += f"   🔧 Replacements: {replacements}\n"
            
            # Get message count for this rule
            async with self.db.execute(
                "SELECT COUNT(*) FROM forwarded_messages WHERE rule_id = ?",
                (rule_id,)
            ) as cursor:
                message_count = (await cursor.fetchone())[0]
                
            rules_text += f"   📊 Messages forwarded: {message_count}\n"
            
            if last_forwarded:
                last_forwarded = datetime.strptime(last_forwarded, "%Y-%m-%d %H:%M:%S")
                rules_text += f"   ⏰ Last forwarded: {last_forwarded.strftime('%Y-%m-%d %H:%M')}\n"
                
            rules_text += "\n"
        
        await update.message.reply_text(rules_text)
    
    async def stop_forward(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop a forwarding rule with enhanced feedback"""
        user_id = update.effective_user.id
        
        # Update last active time
        await self.db.execute(
            "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,)
        )
        await self.db.commit()
        
        # Check if user is verified
        async with self.db.execute("SELECT is_verified FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
        if not user or not user[0]:
            await update.message.reply_text("❌ Please verify your account first using /setup")
            return
        
        if not context.args:
            await update.message.reply_text("Please specify the rule ID to stop. Use /list_rules to see your rules.")
            return
        
        rule_id = context.args[0]
        
        # Verify the rule belongs to the user
        async with self.db.execute(
            "SELECT id FROM forwarding_rules WHERE id = ? AND user_id = ?",
            (rule_id, user_id)
        ) as cursor:
            rule = await cursor.fetchone()
            
        if not rule:
            await update.message.reply_text("❌ Rule not found or you don't have permission to modify it.")
            return
        
        async with self.db.execute(
            "UPDATE forwarding_rules SET is_active = 0 WHERE id = ?",
            (rule_id,)
        ) as cursor:
            await self.db.commit()
            
            if cursor.rowcount > 0:
                # Get message count for this rule
                async with self.db.execute(
                    "SELECT COUNT(*) FROM forwarded_messages WHERE rule_id = ?",
                    (rule_id,)
                ) as cursor:
                    message_count = (await cursor.fetchone())[0]
                    
                await update.message.reply_text(
                    f"✅ Forwarding rule #{rule_id} has been stopped.\n"
                    f"📊 Total messages forwarded: {message_count}"
                )
            else:
                await update.message.reply_text("❌ Error stopping the rule. Please try again.")
    
    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Broadcast message to all users (admin only) with enhanced feedback"""
        if not context.args:
            await update.message.reply_text("Please provide a message to broadcast. Example: /broadcast Hello everyone!")
            return
        
        message = " ".join(context.args)
        
        async with self.db.execute("SELECT user_id FROM users WHERE is_verified = 1") as cursor:
            users = await cursor.fetchall()
        
        if not users:
            await update.message.reply_text("❌ No verified users found.")
            return
        
        # Send broadcast in chunks to avoid rate limiting
        success_count = 0
        fail_count = 0
        total_users = len(users)
        
        status_message = await update.message.reply_text(
            f"📤 Sending broadcast to {total_users} users...\n"
            f"✅ Successful: 0\n"
            f"❌ Failed: 0"
        )
        
        for i, (user_id,) in enumerate(users):
            try:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=f"📢 Announcement from admin:\n\n{message}"
                )
                success_count += 1
                
                # Update status every 10 messages
                if i % 10 == 0:
                    await status_message.edit_text(
                        f"📤 Sending broadcast to {total_users} users...\n"
                        f"✅ Successful: {success_count}\n"
                        f"❌ Failed: {fail_count}\n"
                        f"📊 Progress: {i+1}/{total_users}"
                    )
                
                await asyncio.sleep(0.1)  # Rate limiting
            except (BadRequest, TelegramError) as e:
                logger.error(f"Failed to send broadcast to {user_id}: {e}")
                fail_count += 1
        
        await status_message.edit_text(
            f"✅ Broadcast completed:\n"
            f"✅ Successful: {success_count}\n"
            f"❌ Failed: {fail_count}\n"
            f"📊 Total: {total_users}"
        )
    
    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show enhanced bot statistics (admin only)"""
        # User statistics
        async with self.db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        
        async with self.db.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1") as cursor:
            verified_users = (await cursor.fetchone())[0]
        
        # Rule statistics
        async with self.db.execute("SELECT COUNT(*) FROM forwarding_rules") as cursor:
            total_rules = (await cursor.fetchone())[0]
        
        async with self.db.execute("SELECT COUNT(*) FROM forwarding_rules WHERE is_active = 1") as cursor:
            active_rules = (await cursor.fetchone())[0]
        
        # Message statistics
        async with self.db.execute("SELECT COUNT(*) FROM forwarded_messages") as cursor:
            total_messages = (await cursor.fetchone())[0]
        
        # Recent activity
        async with self.db.execute(
            "SELECT COUNT(*) FROM users WHERE last_active > datetime('now', '-1 day')"
        ) as cursor:
            active_today = (await cursor.fetchone())[0]
        
        stats_text = (
            f"🤖 **Bot Statistics**\n\n"
            f"👥 Users: {total_users} total, {verified_users} verified\n"
            f"📈 Active today: {active_today} users\n"
            f"🔄 Forwarding Rules: {total_rules} total, {active_rules} active\n"
            f"📨 Messages Forwarded: {total_messages}\n"
        )
        
        await update.message.reply_text(stats_text)
    
    async def user_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed user statistics (admin only)"""
        if not context.args:
            await update.message.reply_text("Please specify a user ID. Example: /user_stats 123456789")
            return
        
        user_id = int(context.args[0])
        
        # Get user info
        async with self.db.execute(
            "SELECT phone, is_verified, created_at, last_active FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            user = await cursor.fetchone()
        
        if not user:
            await update.message.reply_text("❌ User not found.")
            return
        
        phone, is_verified, created_at, last_active = user
        
        # Get user's forwarding rules
        async with self.db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) FROM forwarding_rules WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            rules = await cursor.fetchone()
        
        total_rules, active_rules = rules if rules else (0, 0)
        
        # Get user's forwarded messages count
        async with self.db.execute(
            """SELECT COUNT(*) FROM forwarded_messages fm 
               JOIN forwarding_rules fr ON fm.rule_id = fr.id 
               WHERE fr.user_id = ?""",
            (user_id,)
        ) as cursor:
            message_count = (await cursor.fetchone())[0]
        
        stats_text = (
            f"👤 **User Statistics**\n\n"
            f"🆔 User ID: {user_id}\n"
            f"📞 Phone: {phone if phone else 'Not provided'}\n"
            f"✅ Verified: {'Yes' if is_verified else 'No'}\n"
            f"📅 Joined: {created_at}\n"
            f"⏰ Last Active: {last_active if last_active else 'Never'}\n"
            f"🔄 Rules: {total_rules} total, {active_rules} active\n"
            f"📨 Messages Forwarded: {message_count}\n"
        )
        
        await update.message.reply_text(stats_text)
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Cancel the current operation"""
        user_id = update.effective_user.id
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        # Add button handlers if needed
    
    async def run(self):
        """Run the bot with enhanced initialization"""
        await self.init_db()
        
        # Load existing user sessions
        async with self.db.execute("SELECT user_id, session_string FROM users WHERE session_string IS NOT NULL AND is_verified = 1") as cursor:
            users = await cursor.fetchall()
            
            for user_id, session_string in users:
                try:
                    client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
                    await client.connect()
                    
                    # Test the connection
                    await client.get_me()
                    
                    self.user_clients[user_id] = client
                    logger.info(f"Restored session for user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to restore session for user {user_id}: {e}")
        
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("Bot is now running...")
        
        # Keep the application running
        await self.application.updater.idle()
        
    async def shutdown(self):
        """Shutdown the bot gracefully"""
        # Disconnect all user clients
        for user_id, client in self.user_clients.items():
            if client.is_connected():
                await client.disconnect()
        
        # Cancel all forwarding tasks
        for task in self.forwarding_tasks.values():
            task.cancel()
        
        await self.application.stop()
        await self.application.shutdown()
        await self.db.close()

# Main execution
if __name__ == "__main__":
    # Replace with your actual values
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # From BotFather
    OWNER_ID = 123456789  # Your Telegram user ID
    API_ID = 123456  # Your Telegram API ID from https://my.telegram.org
    API_HASH = "your_api_hash_here"  # Your Telegram API Hash
    
    # Optional: Configure SMS service for OTP delivery
    # SMS_SERVICE = SomeSmsService(api_key="your_api_key")
    SMS_SERVICE = None  # Set to None to send OTP via Telegram message
    
    bot = EnhancedAutoForwardBot(BOT_TOKEN, OWNER_ID, API_ID, API_HASH, SMS_SERVICE)
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        asyncio.run(bot.shutdown())