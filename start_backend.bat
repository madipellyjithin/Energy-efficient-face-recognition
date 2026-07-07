@echo off
setlocal
cd /d "C:\Users\allad\Downloads\split_face_system"
set "BACKEND_HOST=0.0.0.0"
set "BACKEND_PORT=5000"
"C:\Users\allad\Downloads\split_face_system\.venv\Scripts\python.exe" "python_server\app.py"
