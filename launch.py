import webbrowser
import threading
import os

def open_browser():
    webbrowser.open_new("http://localhost:8501")

threading.Timer(1.0, open_browser).start()
os.system("streamlit run app.py")
