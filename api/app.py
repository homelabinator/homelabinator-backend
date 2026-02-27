from flask import Flask, request, jsonify, abort
import hashlib
import os
import csv
import subprocess
import shutil
from jinja2 import Template

app = Flask(__name__)

# Configuration
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000/isos")
ISO_STORAGE_DIR = "isos"
CSV_DATABASE = "iso_mappings.csv"
BUILD_DIR = "../nixos-wizard"
RESULT_DIR = "../nixos-wizard/result/iso"
TEMPLATE_SOURCE = "nixos_template.nix"
OUTPUT_CONFIG = "configuration.nix"

# Ensure directories exist
os.makedirs(ISO_STORAGE_DIR, exist_ok=True)

def get_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def check_csv(hash_val):
    if not os.path.exists(CSV_DATABASE):
        return None
    with open(CSV_DATABASE, mode='r', newline='') as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == hash_val:
                return row[1]
    return None

def save_to_csv(hash_val, file_path):
    file_exists = os.path.exists(CSV_DATABASE)
    with open(CSV_DATABASE, mode='a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([hash_val, file_path])

@app.route('/generate-iso', methods=['POST'])
def handle_generate_iso():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    uploaded_file = request.files['file']
    if uploaded_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    content = uploaded_file.read().decode('utf-8')
    md5_hash = get_md5(content)

    # 1. Check if hash exists
    existing_path = check_csv(md5_hash)
    if existing_path:
        filename = os.path.basename(existing_path)
        return jsonify({
            "status": "exists",
            "hash": md5_hash,
            "url": f"{BASE_URL}/{md5_hash}/{filename}"
        })

    # 2. Render Jinja template
    with open(TEMPLATE_SOURCE, 'r') as f:
        template = Template(f.read())
    
    rendered_content = template.render(user_content=content)
    with open(OUTPUT_CONFIG, 'w') as f:
        f.write(rendered_content)

    # 3. Run nix build
    # Using shell=True as the command contains shell-specific syntax (.#...)
    build_cmd = "nix build .#nixosConfigurations.installerIso.config.system.build.isoImage"
    try:
        subprocess.run(build_cmd, shell=True, check=True, cwd=BUILD_DIR) 
    except subprocess.CalledProcessError as e:
        return jsonify({"error": "Nix build failed", "details": str(e)}), 500

    # 4. Find and move ISO
    if not os.path.exists(RESULT_DIR):
        return jsonify({"error": f"Build directory {RESULT_DIR} not found"}), 500

    iso_files = [f for f in os.listdir(RESULT_DIR) if f.endswith('.iso')]
    if not iso_files:
        return jsonify({"error": "No ISO file found in result directory"}), 500
    
    source_iso_name = iso_files[0]
    source_iso_path = os.path.join(RESULT_DIR, source_iso_name)
    
    target_dir = os.path.join(ISO_STORAGE_DIR, md5_hash)
    os.makedirs(target_dir, exist_ok=True)
    target_iso_path = os.path.join(target_dir, source_iso_name)
    
    shutil.copy2(source_iso_path, target_iso_path)

    # 5. Update CSV
    save_to_csv(md5_hash, target_iso_path)

    return jsonify({
        "status": "created",
        "hash": md5_hash,
        "url": f"{BASE_URL}/{md5_hash}/{source_iso_name}"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
