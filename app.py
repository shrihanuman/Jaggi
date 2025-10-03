from flask import Flask, request, jsonify
import threading
import os
from main import bot, db
from admin import AdminPanel

app = Flask(__name__)

# Environment variables से automatically fetch हो जाएगा
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = os.getenv('ADMIN_IDS', '').split(',')

# Initialize admin panel with environment variables
admin_panel = AdminPanel(BOT_TOKEN, ADMIN_IDS)

@app.route('/')
def home():
    stats = db.get_bot_stats()
    return jsonify({
        "status": "Bot is running",
        "stats": stats,
        "bot_token_set": bool(BOT_TOKEN),
        "admin_ids": ADMIN_IDS
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "bot": "running"})

def run_bot():
    """Run the bot in polling mode"""
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Bot error: {e}")
        # Restart after delay
        time.sleep(10)
        run_bot()

def run_admin():
    """Run the admin panel"""
    try:
        admin_panel.start_admin_panel()
    except Exception as e:
        print(f"Admin panel error: {e}")
        # Restart after delay
        time.sleep(10)
        run_admin()

if __name__ == '__main__':
    print("🚀 Starting Terabox Bot...")
    print(f"📊 Bot Token: {'Set' if BOT_TOKEN else 'Not Set'}")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    
    # Start bot and admin in separate threads
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    admin_thread = threading.Thread(target=run_admin, daemon=True)
    
    bot_thread.start()
    admin_thread.start()
    
    # Run Flask app
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Web server starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
