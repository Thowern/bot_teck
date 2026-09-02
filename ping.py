from flask import Flask
app = Flask(__name__)

@app.route("/")
@app.route("/ping")
def ping():
    return "OK", 200