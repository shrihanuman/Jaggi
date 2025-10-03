import sqlite3
import json
import logging
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path="terabox_bot.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    download_count INTEGER DEFAULT 0,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned INTEGER DEFAULT 0
                )
            ''')
            
            # Downloads table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    file_name TEXT,
                    file_size TEXT,
                    download_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'success',
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Admin settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    setting_key TEXT UNIQUE,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Force subscribe channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS force_subscribe (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE,
                    channel_name TEXT,
                    channel_link TEXT,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert default settings
            default_settings = [
                ('bot_status', 'active'),
                ('maintenance_mode', 'false'),
                ('max_file_size', '2GB'),
                ('welcome_message', 'Welcome to Terabox Downloader Bot!'),
                ('broadcast_message', ''),
            ]
            
            for key, value in default_settings:
                cursor.execute('''
                    INSERT OR IGNORE INTO admin_settings (setting_key, setting_value)
                    VALUES (?, ?)
                ''', (key, value))
            
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
    
    def get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    # User management methods
    def add_user(self, user_id, username, first_name, last_name):
        """Add new user to database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, last_active)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, username, first_name, last_name))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def update_user_activity(self, user_id):
        """Update user last activity"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users 
                SET last_active = CURRENT_TIMESTAMP, 
                    download_count = download_count + 1
                WHERE user_id = ?
            ''', (user_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error updating user activity: {e}")
            return False
    
    def get_user_stats(self, user_id):
        """Get user statistics"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT user_id, username, first_name, join_date, download_count, last_active
                FROM users WHERE user_id = ?
            ''', (user_id,))
            
            user = cursor.fetchone()
            conn.close()
            
            if user:
                return {
                    'user_id': user[0],
                    'username': user[1],
                    'first_name': user[2],
                    'join_date': user[3],
                    'download_count': user[4],
                    'last_active': user[5]
                }
            return None
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            return None
    
    def get_all_users(self):
        """Get all users"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT user_id, username, first_name, join_date, download_count, last_active
                FROM users ORDER BY join_date DESC
            ''')
            
            users = cursor.fetchall()
            conn.close()
            
            user_list = []
            for user in users:
                user_list.append({
                    'user_id': user[0],
                    'username': user[1],
                    'first_name': user[2],
                    'join_date': user[3],
                    'download_count': user[4],
                    'last_active': user[5]
                })
            
            return user_list
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
    
    def get_total_users(self):
        """Get total user count"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM users')
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
        except Exception as e:
            logger.error(f"Error getting total users: {e}")
            return 0
    
    # Download tracking methods
    def add_download(self, user_id, file_name, file_size, status='success'):
        """Add download record"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO downloads (user_id, file_name, file_size, status)
                VALUES (?, ?, ?, ?)
            ''', (user_id, file_name, file_size, status))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding download: {e}")
            return False
    
    def get_recent_downloads(self, limit=10):
        """Get recent downloads"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT d.file_name, d.file_size, d.download_date, u.first_name, u.username
                FROM downloads d
                JOIN users u ON d.user_id = u.user_id
                ORDER BY d.download_date DESC
                LIMIT ?
            ''', (limit,))
            
            downloads = cursor.fetchall()
            conn.close()
            
            download_list = []
            for download in downloads:
                download_list.append({
                    'file_name': download[0],
                    'file_size': download[1],
                    'download_date': download[2],
                    'user_name': download[3],
                    'username': download[4]
                })
            
            return download_list
        except Exception as e:
            logger.error(f"Error getting recent downloads: {e}")
            return []
    
    # Admin settings methods
    def get_setting(self, key, default=None):
        """Get admin setting"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT setting_value FROM admin_settings WHERE setting_key = ?
            ''', (key,))
            
            result = cursor.fetchone()
            conn.close()
            
            return result[0] if result else default
        except Exception as e:
            logger.error(f"Error getting setting: {e}")
            return default
    
    def update_setting(self, key, value):
        """Update admin setting"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (setting_key, setting_value)
                VALUES (?, ?)
            ''', (key, value))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error updating setting: {e}")
            return False
    
    # Force subscribe methods
    def add_force_subscribe_channel(self, channel_id, channel_name, channel_link):
        """Add force subscribe channel"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO force_subscribe 
                (channel_id, channel_name, channel_link)
                VALUES (?, ?, ?)
            ''', (channel_id, channel_name, channel_link))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error adding force subscribe channel: {e}")
            return False
    
    def remove_force_subscribe_channel(self, channel_id):
        """Remove force subscribe channel"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM force_subscribe WHERE channel_id = ?
            ''', (channel_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error removing force subscribe channel: {e}")
            return False
    
    def get_force_subscribe_channels(self):
        """Get all force subscribe channels"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT channel_id, channel_name, channel_link 
                FROM force_subscribe 
                ORDER BY added_date DESC
            ''')
            
            channels = cursor.fetchall()
            conn.close()
            
            channel_list = []
            for channel in channels:
                channel_list.append({
                    'channel_id': channel[0],
                    'channel_name': channel[1],
                    'channel_link': channel[2]
                })
            
            return channel_list
        except Exception as e:
            logger.error(f"Error getting force subscribe channels: {e}")
            return []
    
    def get_bot_stats(self):
        """Get comprehensive bot statistics"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Total users
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            # Today's active users
            cursor.execute('''
                SELECT COUNT(*) FROM users 
                WHERE DATE(last_active) = DATE('now')
            ''')
            today_active = cursor.fetchone()[0]
            
            # Total downloads
            cursor.execute('SELECT COUNT(*) FROM downloads')
            total_downloads = cursor.fetchone()[0]
            
            # Today's downloads
            cursor.execute('''
                SELECT COUNT(*) FROM downloads 
                WHERE DATE(download_date) = DATE('now')
            ''')
            today_downloads = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'total_users': total_users,
                'today_active': today_active,
                'total_downloads': total_downloads,
                'today_downloads': today_downloads
            }
        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {}
