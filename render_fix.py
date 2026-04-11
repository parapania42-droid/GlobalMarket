#!/usr/bin/env python3
# Render deploy hatası çözümü

import subprocess
import sys

def fix_render_deploy():
    print("Render deploy hatası düzeltiliyor...")
    
    # 1. Requirements.txt kontrol
    requirements = """flask
flask-sqlalchemy
psycopg2-binary
werkzeug
"""
    
    with open('requirements.txt', 'w') as f:
        f.write(requirements)
    
    print("✅ requirements.txt düzeltildi")
    
    # 2. Start command için script
    start_script = """#!/bin/bash
python final_app.py
"""
    
    with open('start.sh', 'w') as f:
        f.write(start_script)
    
    print("✅ start.sh oluşturuldu")
    print("✅ Render'da Start Command: bash start.sh")

if __name__ == '__main__':
    fix_render_deploy()
