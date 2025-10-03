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
    def __init__(self, bot_token=None, admin_ids=None):
        # Get from environment variables if not provided
        self.bot_token = bot_token or os.getenv('BOT_TOKEN')
        self.admin_ids = admin_ids or os.getenv('ADMIN_IDS', '').split(',')
        
        if not self.bot_token:
            raise ValueError("Bot token not found in environment variables")
        
        self.bot = telebot.TeleBot(self.bot_token)
        self.db = DatabaseManager()
        
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
            
            # Handle setting toggles
            elif call.data == 'toggle_status':
                self.toggle_bot_status(call)
            elif call.data == 'toggle_maintenance':
                self.toggle_maintenance(call)
            
            # Handle user management
            elif call.data == 'all_users':
                self.show_all_users(call)
            elif call.data == 'export_users':
                self.export_users(call)
            
            # Handle force subscribe
            elif call.data == 'add_channel':
                self.add_channel_prompt(call)
            elif call.data == 'remove_channel':
                self.remove_channel_menu(call)
    
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
            username = f"@{user['username']}" if user['username'] else "No username"
            users_text += f"{i}. {user['first_name']} ({username}) - {user['download_count']} downloads\n"
        
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
    
    def show_all_users(self, call):
        """Show all users with pagination"""
        users = self.db.get_all_users()
        
        users_text = f"👥 <b>All Users ({len(users)})</b>\n\n"
        
        for i, user in enumerate(users[:50], 1):  # Show first 50 users
            username = f"@{user['username']}" if user['username'] else "No username"
            users_text += f"{i}. {user['first_name']} ({username}) - {user['download_count']} downloads\n"
        
        if len(users) > 50:
            users_text += f"\n... and {len(users) - 50} more users"
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="admin_users"))
        
        self.bot.edit_message_text(
            users_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    def export_users(self, call):
        """Export users data"""
        users = self.db.get_all_users()
        
        if not users:
            self.bot.answer_callback_query(call.id, "No users to export!")
            return
        
        # Create CSV data
        csv_data = "User ID,Username,First Name,Join Date,Downloads\n"
        for user in users:
            csv_data += f"{user['user_id']},{user['username'] or 'N/A'},{user['first_name']},{user['join_date']},{user['download_count']}\n"
        
        # Send as file
        self.bot.send_document(
            call.message.chat.id,
            ('users.csv', csv_data.encode()),
            caption=f"📊 Users Export - {len(users)} users"
        )
        self.bot.answer_callback_query(call.id, "Users data exported!")
    
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
    
    def toggle_bot_status(self, call):
        """Toggle bot status"""
        current_status = self.db.get_setting('bot_status', 'active')
        new_status = 'inactive' if current_status == 'active' else 'active'
        
        self.db.update_setting('bot_status', new_status)
        
        self.bot.answer_callback_query(call.id, f"Bot status changed to {new_status}")
        self.settings_menu(call)
    
    def toggle_maintenance(self, call):
        """Toggle maintenance mode"""
        current_mode = self.db.get_setting('maintenance_mode', 'false')
        new_mode = 'true' if current_mode == 'false' else 'false'
        
        self.db.update_setting('maintenance_mode', new_mode)
        
        mode_text = "enabled" if new_mode == 'true' else "disabled"
        self.bot.answer_callback_query(call.id, f"Maintenance mode {mode_text}")
        self.settings_menu(call)
    
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
    
    def add_channel_prompt(self, call):
        """Prompt to add channel"""
        self.bot.edit_message_text(
            "🔗 <b>Add Force Subscribe Channel</b>\n\n"
            "Please send channel information in this format:\n"
            "<code>channel_id channel_name channel_link</code>\n\n"
            "<b>Example:</b>\n"
            "<code>-1001234567890 My_Channel https://t.me/my_channel</code>\n\n"
            "<b>How to get channel ID:</b>\n"
            "1. Add your bot to the channel as admin\n"
            "2. Send any message in channel\n"
            "3. Forward that message to @userinfobot\n"
            "4. Copy the channel ID (starts with -100)",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML'
        )
        
        # Register next step handler
        self.bot.register_next_step_handler(call.message, self.process_add_channel)
    
    def process_add_channel(self, message):
        """Process adding channel"""
        try:
            parts = message.text.split(' ', 2)
            if len(parts) != 3:
                self.bot.reply_to(message, "❌ Invalid format! Use: channel_id channel_name channel_link")
                return
            
            channel_id, channel_name, channel_link = parts
            
            # Validate channel ID
            if not channel_id.startswith('-100'):
                self.bot.reply_to(message, "❌ Invalid channel ID! Must start with -100")
                return
            
            # Add channel to database
            if self.db.add_force_subscribe_channel(channel_id, channel_name, channel_link):
                self.bot.reply_to(message, f"✅ Channel '{channel_name}' added successfully!")
            else:
                self.bot.reply_to(message, "❌ Failed to add channel!")
                
        except Exception as e:
            self.bot.reply_to(message, f"❌ Error: {str(e)}")
    
    def remove_channel_menu(self, call):
        """Show remove channel menu"""
        channels = self.db.get_force_subscribe_channels()
        
        if not channels:
            self.bot.answer_callback_query(call.id, "No channels to remove!")
            return
        
        keyboard = InlineKeyboardMarkup()
        for channel in channels:
            keyboard.add(InlineKeyboardButton(
                f"Remove {channel['channel_name']}",
                callback_data=f"remove_{channel['channel_id']}"
            ))
        
        keyboard.add(InlineKeyboardButton("⬅️ Back", callback_data="admin_force_sub"))
        
        self.bot.edit_message_text(
            "🔗 <b>Remove Force Subscribe Channel</b>\n\n"
            "Select a channel to remove:",
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
        try:
            self.bot.polling(none_stop=True)
        except Exception as e:
            logger.error(f"Admin panel error: {e}")
            # Restart after delay
            import time
            time.sleep(10)
            self.start_admin_panel()

# Usage - Environment variables se automatically fetch hoga
if __name__ == "__main__":
    admin_panel = AdminPanel()
    admin_panel.start_admin_panel()
