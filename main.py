import os
import io
import requests
import librosa
import numpy as np
from flask import Flask, request, jsonify

app = Flask(__name__)

SUPABASE_URL = "https://olpboftfsvldjjopchxk.supabase.co"
SUPABASE_KEY = "sb_publishable_ExJp1pJ72ZQm1BHbvECnkw_urfpNaDd"

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/analyze-one", methods=["POST"])
def analyze_one():
    data = request.get_json(force=True)
    hash_archivo = data.get("hash_archivo")
    url = data.get("url")
    if not hash_archivo or not url:
        return jsonify({"error": "faltan hash_archivo o url"}), 400

    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        y, sr = librosa.load(io.BytesIO(r.content), sr=22050, mono=True)

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr, trim=False)
        bpm = round(float(np.atleast_1d(tempo)[0]), 1)
        duracion = round(float(librosa.get_duration(y=y, sr=sr)), 1)

        import datetime
        patch_url = f"{SUPABASE_URL}/rest/v1/axis_catalogo_musical?hash_archivo=eq.{hash_archivo}"
        resp = requests.patch(
            patch_url,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            json={
                "bpm": bpm,
                "duracion_seg": duracion,
                "fecha_analisis": datetime.datetime.utcnow().isoformat(),
                "motor_analisis": "cloudrun-librosa-v1"
            }
        )

        if resp.status_code not in (200, 204):
            return jsonify({"error": "fallo update en supabase", "detalle": resp.text}), 500

        return jsonify({"ok": True, "hash_archivo": hash_archivo, "bpm": bpm, "duracion_seg": duracion}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
