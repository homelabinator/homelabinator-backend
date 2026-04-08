import hashlib
import os
import csv
import shutil
import re
import asyncio
import requests
from datetime import datetime
from typing import Optional
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Template
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

app = FastAPI()

# Environment configuration
APP_ENV = os.getenv("APP_ENV", "dev")  # default to dev

# Preserve CORS rules
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://beta.homelabinator.com",
        "http://localhost:1313",
        "https://homelabinator.com",
    ],
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Configuration
BASE_URL = os.getenv(
    "BASE_URL",
    "https://api.homelabinator.com"
    if APP_ENV == "prod"
    else "https://beta-api.homelabinator.com",
)
ISO_STORAGE_DIR = Path("isos").resolve()
CSV_DATABASE = Path("iso_mappings.csv").resolve()
BUILD_DIR = Path("../nixos-wizard").resolve()
RESULT_DIR = Path("../nixos-wizard/result/iso").resolve()
TEMPLATE_SOURCE = Path("../nixos-wizard/isoimage/homelabinator-init-script-template.nix").resolve()
OUTPUT_CONFIG = Path("../nixos-wizard/isoimage/homelabinator-init-script.nix").resolve()

# Build lock for queuing
build_lock = asyncio.Lock()

# Ensure directories exist
ISO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def get_md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def check_csv(hash_val: str) -> Optional[str]:
    if not CSV_DATABASE.exists():
        return None
    with CSV_DATABASE.open(mode="r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == hash_val:
                return row[1]
    return None


def save_to_csv(hash_val: str, file_path: str):
    with CSV_DATABASE.open(mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([hash_val, file_path])


@app.get("/isos/{filename:path}")
async def serve_iso(filename: str, request: Request):
    try:
        # Prevent any potential path traversal by resolving and checking relative to base
        # Using filename.lstrip("/") to prevent joining absolute paths
        requested_path = (ISO_STORAGE_DIR / filename.lstrip("/")).resolve()

        if not requested_path.is_relative_to(ISO_STORAGE_DIR):
            return HTMLResponse("<h1>Not Found</h1>", status_code=404)

        if not requested_path.is_file():
            return HTMLResponse("<h1>Not Found</h1>", status_code=404)

        print(f"GET - Downloaded: {datetime.now()} - {requested_path}")
        return FileResponse(requested_path)
    except Exception:
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)


@app.get("/isos")
@app.get("/isos/")
async def isos_index():
    return HTMLResponse("<h1>Not Found</h1>", status_code=404)


@app.post("/generate-iso")
async def handle_generate_iso(file: UploadFile = File(...)):
    if not file.filename:
        return JSONResponse({"error": "No selected file"}, status_code=400)

    content = (await file.read()).decode("utf-8")
    md5_hash = get_md5(content)

    # Validate md5_hash to prevent any path injection
    if not re.fullmatch(r"[a-fA-F0-9]{32}", md5_hash):
        return JSONResponse({"error": "Invalid content hash"}, status_code=400)

    # 1. Check if hash exists
    existing_path = check_csv(md5_hash)
    if existing_path:
        filename = Path(existing_path).name

        async def fast_generator():
            yield {"event": "progress", "data": "100.00"}
            yield {
                "event": "completed",
                "data": f"{BASE_URL}/isos/{md5_hash}/{filename}",
            }

        return EventSourceResponse(fast_generator())

    async def event_generator():
        was_locked = build_lock.locked()
        async with build_lock:
            # 1.5 Re-check if hash exists
            existing_path = check_csv(md5_hash)
            if existing_path:
                filename = Path(existing_path).name
                yield {"event": "progress", "data": "100.00"}
                yield {
                    "event": "completed",
                    "data": f"{BASE_URL}/isos/{md5_hash}/{filename}",
                }
                return

            if was_locked:
                await asyncio.sleep(5)

            progress_bar = 0.0

            # 2. Render Jinja template
            try:
                with TEMPLATE_SOURCE.open("r") as f:
                    template = Template(f.read())

                rendered_content = template.render(user_content=content)
                with OUTPUT_CONFIG.open("w") as f:
                    f.write(rendered_content)
            except Exception as e:
                yield {"event": "error", "data": f"Template rendering failed: {str(e)}"}
                return

            # 3. Run nix build
            build_cmd = "nix build ./isoimage#iso"
            progress_regex = re.compile(r"\[(\d+)/(\d+)/(\d+) built\]")

            try:
                process = await asyncio.create_subprocess_shell(
                    build_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=BUILD_DIR,
                )

                while True:
                    line_bytes = await process.stdout.readline()
                    if not line_bytes:
                        break

                    line = line_bytes.decode("utf-8")
                    print(line, end="", flush=True)

                    if line.startswith("evaluation warning:"):
                        continue

                    match = progress_regex.search(line)
                    new_progress = progress_bar
                    if match:
                        try:
                            p1, p2, p3 = map(float, match.groups())
                            if p3 > 0:
                                factor = 100.0 / p3
                                scaled_p2 = p2 * factor
                                new_progress += scaled_p2
                        except Exception:
                            new_progress += 0.01
                    else:
                        new_progress += 0.01

                    if new_progress > progress_bar:
                        progress_bar = new_progress

                    yield {
                        "event": "progress",
                        "data": f"{min(progress_bar, 100.0):.2f}",
                    }

                await process.wait()
                if process.returncode != 0:
                    yield {"event": "error", "data": "Nix build failed"}
                    return

            except Exception as e:
                yield {"event": "error", "data": str(e)}
                return

            # 4. Find and move ISO
            if not RESULT_DIR.exists():
                yield {
                    "event": "error",
                    "data": f"Build directory {RESULT_DIR} not found",
                }
                return

            iso_files = [f for f in RESULT_DIR.iterdir() if f.is_file() and f.suffix == ".iso"]
            if not iso_files:
                yield {
                    "event": "error",
                    "data": "No ISO file found in result directory",
                }
                return

            source_iso_path = iso_files[0]
            # Use secure_filename to ensure the target filename is safe
            source_iso_name = secure_filename(source_iso_path.name)

            target_dir = ISO_STORAGE_DIR / md5_hash
            target_dir.mkdir(parents=True, exist_ok=True)
            target_iso_path = target_dir / source_iso_name

            # Final safety check: ensure we are writing within ISO_STORAGE_DIR
            if not target_iso_path.resolve().is_relative_to(ISO_STORAGE_DIR):
                 yield {"event": "error", "data": "Invalid target path"}
                 return

            shutil.copy2(source_iso_path, target_iso_path)

            # 5. Update CSV
            save_to_csv(md5_hash, str(target_iso_path))

            yield {
                "event": "completed",
                "data": f"{BASE_URL}/isos/{md5_hash}/{source_iso_name}",
            }

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn

    print(f"Running in {APP_ENV} mode")
    port = int(os.getenv("PORT", 5001 if APP_ENV == "prod" else 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
