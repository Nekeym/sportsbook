from flask import Flask
from threading import Thread

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 8080

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host=FLASK_HOST, port=FLASK_PORT)

def keep_alive():
    t = Thread(target=run)
    t.start()
