from flask import Flask, request, jsonify
import threading
import os
from main import bot, db
from admin import AdminPanel

app = Flask(__name__)

# Initialize admin panel
admin_panel = AdminPanel(
    bot_token=os.getenv('BOT_TOKEN'),
    admin_ids=os.getenv('ADMIN_IDS', '').split(',')
)

@app.route('/')
def home():
    stats = db.get_bot_stats()
    return jsonify({
        "status": "Bot is running",
        "stats": stats
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for Telegram bot"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    return 'Error', 403

def run_bot():
    """Run the bot in polling mode"""
    bot.polling(none_stop=True)

def run_admin():
    """Run the admin panel"""
    admin_panel.start_admin_panel()

if __name__ == '__main__':
    # Start bot and admin in separate threads
    bot_thread = threading.Thread(target=run_bot)
    admin_thread = threading.Thread(target=run_admin)
    
    bot_thread.start()
    admin_thread.start()
    
    # Run Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
