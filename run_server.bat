@echo off
cd /d D:\develope\searching
"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8001 --reload
