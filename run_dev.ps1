# PowerShell helper to create venv, install deps, and run the server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run_server.py
