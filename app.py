from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Hello, World!"

if __name__ == '__main__':
    # Set host to '0.0.0.0' to listen on all IP addresses
    app.run(debug=True, host='0.0.0.0', port=8000)
