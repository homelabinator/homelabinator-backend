import hashlib
import os
import csv
import shutil
import re
import asyncio
import requests
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Template
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Environment configuration
APP_ENV = os.getenv("APP_ENV", "dev")  # default to dev
FORM_URL = os.getenv("FORM_URL")

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
BASE_URL = os.getenv("BASE_URL", "https://api.homelabinator.com")
ISO_STORAGE_DIR = "isos"
CSV_DATABASE = "iso_mappings.csv"
BUILD_DIR = "../nixos-wizard"
RESULT_DIR = "../nixos-wizard/result/iso"
TEMPLATE_SOURCE = "../nixos-wizard/isoimage/homelabinator-init-script-template.nix"
OUTPUT_CONFIG = "../nixos-wizard/isoimage/homelabinator-init-script.nix"

# Build lock for queuing
build_lock = asyncio.Lock()

# Ensure directories exist
os.makedirs(ISO_STORAGE_DIR, exist_ok=True)


def get_md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def check_csv(hash_val: str) -> Optional[str]:
    if not os.path.exists(CSV_DATABASE):
        return None
    with open(CSV_DATABASE, mode="r", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0] == hash_val:
                return row[1]
    return None


def save_to_csv(hash_val: str, file_path: str):
    with open(CSV_DATABASE, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([hash_val, file_path])


@app.get("/isos/{filename:path}")
async def serve_iso(filename: str, request: Request):
    file_path = os.path.join(ISO_STORAGE_DIR, filename)
    if not os.path.isfile(file_path):
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)
    return FileResponse(file_path)


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

    # 1. Check if hash exists
    existing_path = check_csv(md5_hash)
    if existing_path:
        filename = os.path.basename(existing_path)

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
            # 1.5 Re-check if hash exists (another process might have built it while we waited for the lock)
            existing_path = check_csv(md5_hash)
            if existing_path:
                filename = os.path.basename(existing_path)
                yield {"event": "progress", "data": "100.00"}
                yield {
                    "event": "completed",
                    "data": f"{BASE_URL}/isos/{md5_hash}/{filename}",
                }
                return

            if was_locked:
                # If a build was in progress and we are not a cache hit, wait 5 seconds.
                await asyncio.sleep(5)

            progress_bar = 0.0

            # 2. Render Jinja template
            try:
                with open(TEMPLATE_SOURCE, "r") as f:
                    template = Template(f.read())

                rendered_content = template.render(user_content=content)
                with open(OUTPUT_CONFIG, "w") as f:
                    f.write(rendered_content)
            except Exception as e:
                yield {"event": "error", "data": f"Template rendering failed: {str(e)}"}
                return

            # 3. Run nix build
            build_cmd = "nix build ./isoimage#iso"
            # Regex for [1/0/18 built]
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
                    print(line, end="", flush=True)  # Show on server terminal

                    if line.startswith("evaluation warning:"):
                        continue

                    match = progress_regex.search(line)
                    new_progress = progress_bar
                    if match:
                        try:
                            # scale the last number (#3) to be 100
                            # scale the #2 number, and add it to the progress bar as it changes
                            # #1/#2/#3 -> group(1)/group(2)/group(3)
                            p1, p2, p3 = map(float, match.groups())
                            if p3 > 0:
                                factor = 100.0 / p3
                                scaled_p2 = p2 * factor
                                new_progress += scaled_p2
                        except Exception:
                            # Fallback to previous rule
                            new_progress += 0.01
                    else:
                        new_progress += 0.01

                    # Regardless of the scaling, do not let the "progress_bar" variable decrease.
                    if new_progress > progress_bar:
                        progress_bar = new_progress

                    # Cap at 100 for safety
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
            if not os.path.exists(RESULT_DIR):
                yield {
                    "event": "error",
                    "data": f"Build directory {RESULT_DIR} not found",
                }
                return

            iso_files = [f for f in os.listdir(RESULT_DIR) if f.endswith(".iso")]
            if not iso_files:
                yield {
                    "event": "error",
                    "data": "No ISO file found in result directory",
                }
                return

            source_iso_name = iso_files[0]
            source_iso_path = os.path.join(RESULT_DIR, source_iso_name)

            target_dir = os.path.join(ISO_STORAGE_DIR, md5_hash)
            os.makedirs(target_dir, exist_ok=True)
            target_iso_path = os.path.join(target_dir, source_iso_name)

            shutil.copy2(source_iso_path, target_iso_path)

            # 5. Update CSV
            save_to_csv(md5_hash, target_iso_path)

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
