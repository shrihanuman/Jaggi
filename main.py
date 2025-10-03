import os
import requests
import telebot
import json
import logging
import time
import threading
from urllib.parse import urlparse
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telebot import types
import re

# Import database and admin modules
from database import DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot Token (Replace with your actual token)
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')

# Admin IDs (Replace with your Telegram user ID)
ADMIN_IDS = os.getenv('ADMIN_IDS', 'YOUR_USER_ID').split(',')

# Initialize bot and database
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
db = DatabaseManager()

class TeraboxDownloader:
    def __init__(self):
        self.apis = [
            self.api_terabox_dl,
            self.api_tb_botbns,
            self.api_terabox_online,
            self.api_terabox_api
        ]
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.terabox.com/'
        })

    def api_terabox_dl(self, link):
        """API 1: terabox-dl.com"""
        try:
            url = "https://terabox-dl.com/api/get-info"
            payload = {'url': link}
            response = self.session.post(url, data=payload, timeout=45)
            if response.status_code == 200:
                data = response.json()
                logger.info(f"API1 Success: {data.get('filename', 'Unknown')}")
                return self.format_response(data)
            return None
        except Exception as e:
            logger.error(f"API1 Error: {e}")
            return None

    def api_tb_botbns(self, link):
        """API 2: tb.botbns.xyz"""
        try:
            url = "https://tb.botbns.xyz/api/getInfo"
            payload = {'url': link}
            response = self.session.post(url, json=payload, timeout=45)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    file_data = data.get('data', {})
                    logger.info(f"API2 Success: {file_data.get('filename', 'Unknown')}")
                    return self.format_response(file_data)
            return None
        except Exception as e:
            logger.error(f"API2 Error: {e}")
            return None

    def format_response(self, data):
        """Format API response consistently"""
        if not data:
            return None

        result = {
            'filename': data.get('filename', 'Unknown File'),
            'size': data.get('size', 'Unknown Size'),
            'duration': data.get('duration', ''),
            'download_url': data.get('download_url', ''),
            'qualities': {}
        }

        # Handle different quality formats
        if data.get('qualities'):
            result['qualities'] = data['qualities']
        elif data.get('download_links'):
            result['qualities'] = {'Direct': data['download_links']}
        elif data.get('url'):
            result['download_url'] = data['url']

        return result

    def get_download_info(self, link):
        """Try all APIs with proper error handling"""
        logger.info(f"Processing link: {link}")
        
        for i, api_method in enumerate(self.apis):
            try:
                logger.info(f"Trying API {i+1}...")
                result = api_method(link)
                if result and (result.get('download_url') or result.get('qualities')):
                    logger.info(f"API {i+1} successful!")
                    return result
                time.sleep(1)  # Avoid rate limiting
            except Exception as e:
                logger.error(f"API {i+1} failed: {e}")
                continue
        
        return None

# Initialize downloader
downloader = TeraboxDownloader()

def is_terabox_link(text):
    """Check if text is a valid Terabox link"""
    patterns = [
        r'https?://(www\.)?terabox\.com/[^\s]+',
        r'https?://(www\.)?1024terabox\.com/[^\s]+',
        r'https?://(www\.)?teraboxapp\.com/[^\s]+'
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    return False

def format_file_size(size_str):
    """Format file size for better display"""
    if not size_str or size_str == 'Unknown Size':
        return 'Unknown Size'
    
    size_str = re.sub(r'[^\d.]', '', size_str)
    if not size_str:
        return 'Unknown Size'
    
    try:
        size_bytes = float(size_str)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    except:
        return 'Unknown Size'

def check_force_subscribe(user_id):
    """Check if user is subscribed to required channels"""
    channels = db.get_force_subscribe_channels()
    
    if not channels:
        return True, None  # No channels set
    
    for channel in channels:
        try:
            chat_member = bot.get_chat_member(channel['channel_id'], user_id)
            if chat_member.status in ['left', 'kicked']:
                return False, channel
        except Exception as e:
            logger.error(f"Error checking channel subscription: {e}")
            continue
    
    return True, None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Send welcome message with force subscribe check"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Add user to database
    db.add_user(user_id, username, first_name, last_name)
    
    # Check force subscribe
    is_subscribed, channel = check_force_subscribe(user_id)
    
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(
            f"Join {channel['channel_name']}", 
            url=channel['channel_link']
        ))
        keyboard.add(InlineKeyboardButton(
            "✅ I've Joined", 
            callback_data="check_subscription"
        ))
        
        bot.send_message(
            message.chat.id,
            f"📢 <b>Please Subscribe!</b>\n\n"
            f"To use this bot, please join our channel first:\n"
            f"📢 {channel['channel_name']}\n\n"
            f"After joining, click the button below:",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        return
    
    # User is subscribed, show welcome
    welcome_text = """
<b>🚀 TERABOX DOWNLOADER BOT</b>

<i>मैं किसी भी size की Terabox files को download कर सकता हूँ! (2GB+ तक)</i>

<b>📌 How to Use:</b>
1. Terabox की किसी भी link को यहाँ paste करें
2. Bot automatically file information fetch करेगा
3. Download button पर click करें

<b>✅ Supported Files:</b>
• Videos (MP4, MKV, AVI, MOV) - 2GB+ तक
• Audio (MP3, M4A, WAV, FLAC)
• Documents (PDF, ZIP, RAR, DOC)
• Images (JPG, PNG, GIF, WEBP)

<b>🔧 Commands:</b>
/start - Bot start करें
/help - Help message
/stats - Your statistics

<b>⚠️ Note:</b>
• Large files को download करने में time लग सकता है
• Internet speed के according download time vary करेगा
    """
    
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add('📋 How to Use', '🔧 Support')
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def handle_subscription_check(call):
    """Handle subscription check"""
    user_id = call.from_user.id
    is_subscribed, channel = check_force_subscribe(user_id)
    
    if is_subscribed:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_welcome(call.message)
    else:
        bot.answer_callback_query(
            call.id,
            f"❌ Please join {channel['channel_name']} first!",
            show_alert=True
        )

@bot.message_handler(commands=['stats'])
def show_stats(message):
    """Show user statistics"""
    user_id = message.from_user.id
    user_stats = db.get_user_stats(user_id)
    
    if user_stats:
        stats_text = f"""
<b>📊 YOUR STATISTICS</b>

<b>User:</b> {user_stats['first_name']} (@{user_stats['username']})
<b>Join Date:</b> {user_stats['join_date']}
<b>Total Downloads:</b> {user_stats['download_count']}
<b>Last Active:</b> {user_stats['last_active']}
        """
    else:
        stats_text = "No statistics available."
    
    bot.send_message(message.chat.id, stats_text)

@bot.message_handler(func=lambda message: message.text in ['📋 How to Use', '🔧 Support'])
def handle_buttons(message):
    """Handle button clicks"""
    if message.text == '📋 How to Use':
        help_text = """
<b>📖 HOW TO USE</b>

1. <b>Copy Terabox Link:</b>
   • Terabox app या website से file की link copy करें

2. <b>Paste Here:</b>
   • Link को directly यहाँ paste कर दें

3. <b>Wait:</b>
   • Bot automatically file information fetch करेगा

4. <b>Download:</b>
   • Download button पर click करें

<b>Example Links:</b>
<code>https://terabox.com/s/xxxxxxxxxxxx</code>
<code>https://www.terabox.com/sharing/xxxxxxxx</code>
        """
        bot.send_message(message.chat.id, help_text, disable_web_page_preview=True)
    
    elif message.text == '🔧 Support':
        support_text = """
<b>🔧 SUPPORT</b>

<b>If facing issues:</b>
• Valid Terabox link check करें
• Internet connection check करें
• कुछ minutes बाद फिर try करें
• Large files के लिए wait करें

<b>Common Issues:</b>
• Invalid link - Correct format use करें
• File not found - Link check करें
• Server busy - Wait और retry करें
        """
        bot.send_message(message.chat.id, support_text)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Handle all incoming messages"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Check force subscribe first
    is_subscribed, channel = check_force_subscribe(user_id)
    if not is_subscribed:
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(
            f"Join {channel['channel_name']}", 
            url=channel['channel_link']
        ))
        keyboard.add(InlineKeyboardButton(
            "✅ I've Joined", 
            callback_data="check_subscription"
        ))
        
        bot.send_message(
            message.chat.id,
            f"❌ <b>Subscription Required!</b>\n\n"
            f"Please join {channel['channel_name']} to use this bot.",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        return
    
    # Check if it's a Terabox link
    if not is_terabox_link(text):
        bot.reply_to(message, 
            "❌ <b>Invalid Terabox Link!</b>\n\n"
            "कृपया एक valid Terabox link भेजें।\n\n"
            "<b>Example:</b>\n"
            "<code>https://terabox.com/s/xxxxxxxx</code>\n"
            "<code>https://www.terabox.com/sharing/xxxxxxxx</code>",
            disable_web_page_preview=True
        )
        return
    
    # Check maintenance mode
    if db.get_setting('maintenance_mode') == 'true':
        bot.reply_to(message,
            "🔧 <b>Bot Under Maintenance</b>\n\n"
            "The bot is currently under maintenance. Please try again later.",
            disable_web_page_preview=True
        )
        return
    
    # Send processing message
    processing_msg = bot.reply_to(message, 
        "⏳ <b>Processing Your Link...</b>\n\n"
        "File information fetch की जा रही है।\n"
        "कृपया wait करें...",
        disable_web_page_preview=True
    )
    
    # Get download information
    try:
        file_info = downloader.get_download_info(text)
        
        if not file_info:
            bot.edit_message_text(
                "❌ <b>Download Failed!</b>\n\n"
                "Possible reasons:\n"
                "• Invalid या expired link\n"
                "• File removed हो गया है\n"
                "• Server temporary unavailable\n"
                "• Link password protected है\n\n"
                "कृपया:\n"
                "✅ Link validity check करें\n"
                "✅ कुछ देर बाद try करें\n"
                "✅ Different link try करें",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                disable_web_page_preview=True
            )
            return
        
        # Create download buttons
        keyboard = InlineKeyboardMarkup()
        
        # Add direct download button
        if file_info.get('download_url'):
            keyboard.add(InlineKeyboardButton(
                "📥 DIRECT DOWNLOAD", 
                url=file_info['download_url']
            ))
        
        # Add quality buttons if available
        if file_info.get('qualities'):
            for quality, url in file_info['qualities'].items():
                if isinstance(url, str) and url.startswith('http'):
                    keyboard.add(InlineKeyboardButton(
                        f"🎬 {quality.upper()} QUALITY", 
                        url=url
                    ))
        
        # Add retry button
        keyboard.add(InlineKeyboardButton(
            "🔄 TRY ANOTHER LINK", 
            callback_data="new_link"
        ))
        
        # Format file information
        filename = file_info.get('filename', 'Unknown File')
        size = format_file_size(file_info.get('size'))
        duration = file_info.get('duration', 'N/A')
        
        # Update user activity and add download record
        db.update_user_activity(user_id)
        db.add_download(user_id, filename, size)
        
        # Prepare success message
        success_text = f"""
✅ <b>DOWNLOAD READY!</b>

📁 <b>File:</b> <code>{filename}</code>
💾 <b>Size:</b> <code>{size}</code>
⏱️ <b>Duration:</b> <code>{duration}</code>

⬇️ <b>Download options नीचे दिए गए हैं:</b>

<b>Note:</b> Large files को download करने में time लग सकता है।
        """
        
        bot.edit_message_text(
            success_text,
            chat_id=message.chat.id,
            message_id=processing_msg.message_id,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error in handle_all_messages: {e}")
        bot.edit_message_text(
            "❌ <b>Unexpected Error Occurred!</b>\n\n"
            "कृपया कुछ देर बाद फिर से try करें।\n"
            "Technical team को inform किया गया है।",
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )

@bot.callback_query_handler(func=lambda call: call.data == "new_link")
def handle_new_link(call):
    """Handle new link request"""
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "🔄 <b>Send New Terabox Link</b>\n\n"
        "अब आप नया Terabox link भेज सकते हैं।",
        disable_web_page_preview=True
    )

def main():
    """Main function to start the bot"""
    logger.info("Starting Terabox Downloader Bot...")
    
    try:
        # Test bot connection
        bot_info = bot.get_me()
        logger.info(f"Bot started successfully: @{bot_info.username}")
        
        # Start polling
        bot.polling(none_stop=True, interval=2, timeout=60)
        
    except Exception as e:
        logger.error(f"Bot failed to start: {e}")
        time.sleep(30)
        main()  # Restart bot

if __name__ == "__main__":
    # Create necessary directories
    os.makedirs('logs', exist_ok=True)
    
    # Start the bot
    while True:
        try:
            main()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            logger.info("Restarting bot in 10 seconds...")
            time.sleep(10)
