import os
import logging
import sqlite3
from datetime import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Import database manager
from database import DatabaseManager

logger = logging.getLogger(__name__)

class AdminPanel:
    def __init__(self, bot_token, admin_ids):
        self.bot = telebot.TeleBot(bot_token)
        self.db = DatabaseManager()
        self.admin_ids = admin_ids  # List of admin user IDs
        
        # Setup admin handlers
        self.setup_admin_handlers()
    
    def is_admin(self, user_id):
        """Check if user is admin"""
        return str(user_id) in self.admin_ids
    
    def setup_admin_handlers(self):
        """Setup admin command handlers"""
        
        @self.bot.message_handler(commands=['admin'])
        def admin_panel(message):
            """Admin panel main menu"""
            if not self.is_admin(message.from_user.id):
                self.bot.reply_to(message, "❌ Access Denied!")
                return
            
            keyboard = InlineKeyboardMarkup()
            keyboard.row(
                InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
                InlineKeyboardButton("👥 Users", callback_data="admin_users")
            )
            keyboard.row(
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")
            )
            keyboard.row(
                InlineKeyboardButton("🔗 Force Subscribe", callback_data="admin_force_sub"),
                InlineKeyboardButton("📥 Downloads", callback_data="admin_downloads")
            )
            
            self.bot.send_message(
                message.chat.id,
                "🛠️ <b>Admin Panel</b>\n\n"
                "Choose an option to manage your bot:",
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        
        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
        def handle_admin_callbacks(call):
            """Handle admin panel callbacks"""
            if not self.is_admin(call.from_user.id):
                self.bot.answer_callback_query(call.id, "❌ Access Denied!")
                return
            
            if call.data == 'admin_stats':
                self.show_statistics(call)
            elif call.data == 'admin_users':
                self.show_users_menu(call)
            elif call.data == 'admin_broadcast':
                self.broadcast_menu(call)
            elif call.data == 'admin_settings':
                self.settings_menu(call)
            elif call.data == 'admin_force_sub':
                self.force_subscribe_menu(call)
            elif call.data == 'admin_downloads':
                self.show_downloads(call)
            elif call.data == 'back_to_admin':
                self.back_to_admin(call)
    
    def show_statistics(self, call):
        """Show bot statistics"""
        stats = self.db.get_bot_stats()
        recent_downloads = self.db.get_recent_downloads(5)
        
        stats_text = f"""
📊 <b>Bot Statistics</b>

👥 <b>Users:</b>
• Total Users: {stats.get('total_users', 0)}
• Today Active: {stats.get('today_active', 0)}

📥 <b>Downloads:</b>
• Total Downloads: {stats.get('total_downloads', 0)}
• Today Downloads: {stats.get('today_downloads', 0)}

🕒 <b>Recent Downloads:</b>
"""
        
        for i, download in enumerate(recent_downloads, 1):
            stats_text += f"{i}. {download['file_name']} - {download['user_name']}\n"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats"))
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        
        self.bot.edit_message_text(
            stats_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def show_users_menu(self, call):
        """Show users management menu"""
        total_users = self.db.get_total_users()
        recent_users = self.db.get_all_users()[:5]
        
        users_text = f"""
👥 <b>Users Management</b>

• Total Users: {total_users}

<b>Recent Users:</b>
"""
        
        for i, user in enumerate(recent_users, 1):
            users_text += f"{i}. {user['first_name']} (@{user['username']}) - {user['download_count']} downloads\n"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("📜 All Users", callback_data="all_users"),
            InlineKeyboardButton("📧 Export Users", callback_data="export_users")
        )
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        
        self.bot.edit_message_text(
            users_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def broadcast_menu(self, call):
        """Broadcast message menu"""
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📢 Send Broadcast", callback_data="send_broadcast"))
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        
        self.bot.edit_message_text(
            "📢 <b>Broadcast Message</b>\n\n"
            "Send a message to all users. Use this feature carefully!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def settings_menu(self, call):
        """Bot settings menu"""
        bot_status = self.db.get_setting('bot_status', 'active')
        maintenance = self.db.get_setting('maintenance_mode', 'false')
        max_size = self.db.get_setting('max_file_size', '2GB')
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton(f"Status: {bot_status}", callback_data="toggle_status"),
            InlineKeyboardButton(f"Maintenance: {maintenance}", callback_data="toggle_maintenance")
        )
        keyboard.row(
            InlineKeyboardButton(f"Max Size: {max_size}", callback_data="change_max_size"),
            InlineKeyboardButton("Edit Welcome", callback_data="edit_welcome")
        )
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        
        self.bot.edit_message_text(
            "⚙️ <b>Bot Settings</b>\n\n"
            "Configure your bot settings:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def force_subscribe_menu(self, call):
        """Force subscribe management menu"""
        channels = self.db.get_force_subscribe_channels()
        
        channels_text = "🔗 <b>Force Subscribe Channels</b>\n\n"
        
        if channels:
            for i, channel in enumerate(channels, 1):
                channels_text += f"{i}. {channel['channel_name']} ({channel['channel_id']})\n"
        else:
            channels_text += "No channels added yet.\n"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("➕ Add Channel", callback_data="add_channel"),
            InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel")
        )
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        
        self.bot.edit_message_text(
            channels_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def show_downloads(self, call):
        """Show recent downloads"""
        downloads = self.db.get_recent_downloads(10)
        
        downloads_text = "📥 <b>Recent Downloads</b>\n\n"
        
        for i, download in enumerate(downloads, 1):
            downloads_text += f"{i}. <b>{download['file_name']}</b>\n"
            downloads_text += f"   👤 {download['user_name']} | 💾 {download['file_size']}\n"
            downloads_text += f"   🕒 {download['download_date']}\n\n"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔄 Refresh", callback_data="admin_downloads"))
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="back_to_admin"))
        
        self.bot.edit_message_text(
            downloads_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def back_to_admin(self, call):
        """Back to admin main menu"""
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
            InlineKeyboardButton("👥 Users", callback_data="admin_users")
        )
        keyboard.row(
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")
        )
        keyboard.row(
            InlineKeyboardButton("🔗 Force Subscribe", callback_data="admin_force_sub"),
            InlineKeyboardButton("📥 Downloads", callback_data="admin_downloads")
        )
        
        self.bot.edit_message_text(
            "🛠️ <b>Admin Panel</b>\n\n"
            "Choose an option to manage your bot:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def start_admin_panel(self):
        """Start the admin panel"""
        logger.info("Admin panel started")
        self.bot.polling(none_stop=True)

# Usage example
if __name__ == "__main__":
    # Add your bot token and admin user IDs
    BOT_TOKEN = "YOUR_ADMIN_BOT_TOKEN"
    ADMIN_IDS = ["YOUR_USER_ID"]  # Your Telegram user ID
    
    admin_panel = AdminPanel(BOT_TOKEN, ADMIN_IDS)
    admin_panel.start_admin_panel()
