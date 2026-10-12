import os
import gc
import tempfile
import requests
import librosa
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=[
    "https://boxdj.lovable.app",
    "https://music-stacker-pro.lovable.app",
    "https://id-preview--26fcdc32-f9c1-45ba-aa57-5bf9395d5d43.lovable.app"
])

SUPABASE_URL = "https://olpboftfsvldjjopchxk.supabase.co"
SUPABASE_KEY = "sb_publishable_ExJp1pJ72ZQm1BHbvECnkw_urfpNaDd"

MOTOR = "cloudrun-librosa-v2-90s"
SEGMENTO_SEG = 90          # analizamos solo 90 s del medio del tema
MAX_DESCARGA_MB = 60       # tope de seguridad para el archivo


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "motor": MOTOR}), 200


def descargar_a_disco(url):
    """Baja el audio por partes a un archivo real en disco (no a memoria)."""
    suffix = os.path.splitext(url.split("?")[0])[1] or ".audio"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    total = 0
    try:
        with requests.get(url, timeout=60, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DESCARGA_MB * 1024 * 1024:
                    raise ValueError(f"archivo demasiado grande (> {MAX_DESCARGA_MB} MB)")
                tmp.write(chunk)
    finally:
        tmp.close()
    return tmp.name


@app.route("/analyze-one", methods=["POST"])
def analyze_one():
    data = request.get_json(force=True)
    hash_archivo = data.get("hash_archivo")
    url = data.get("url")
    if not hash_archivo or not url:
        return jsonify({"error": "faltan hash_archivo o url"}), 400

    tmp_path = None
    try:
        tmp_path = descargar_a_disco(url)

        # Duracion total del tema (lee solo el encabezado, casi no usa memoria)
        try:
            dur_total = float(librosa.get_duration(path=tmp_path))
        except Exception:
            dur_total = None

        # Si el tema es largo, tomamos 90 s del medio: alcanza para el BPM,
        # evita intros lentas y usa mucha menos memoria.
        offset = 0.0
        duration = None
        if dur_total and dur_total > SEGMENTO_SEG + 10:
            offset = (dur_total - SEGMENTO_SEG) / 2.0
            duration = float(SEGMENTO_SEG)

        y, sr = librosa.load(tmp_path, sr=22050, mono=True,
                             offset=offset, duration=duration)

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr, trim=False)
        bpm = round(float(np.atleast_1d(tempo)[0]), 1)
        if dur_total is None:
            dur_total = float(librosa.get_duration(y=y, sr=sr))
        duracion = round(float(dur_total), 1)

        del y
        gc.collect()

        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/catalogo_guardar_analisis",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "p_hash": hash_archivo,
                "p_bpm": bpm,
                "p_duracion": duracion,
                "p_motor": MOTOR
            },
            timeout=30
        )

        if resp.status_code != 200:
            return jsonify({"error": "fallo guardado en supabase", "detalle": resp.text}), 500

        if resp.text.strip() != "true":
            return jsonify({
                "error": "no se guardo: el tema ya tiene BPM o el hash no existe",
                "hash_archivo": hash_archivo, "bpm": bpm, "duracion_seg": duracion
            }), 409

        return jsonify({"ok": True, "hash_archivo": hash_archivo,
                        "bpm": bpm, "duracion_seg": duracion}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
