import os
import io
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

        # Bajamos a un archivo REAL en disco, no a memoria -esto habilita
        # que librosa use ffmpeg como respaldo para formatos como .m4a,
        # cosa que no puede hacer bien leyendo desde BytesIO.
        suffix = os.path.splitext(url.split("?")[0])[1] or ".audio"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(r.content)
            tmp_path = tmp.name

        try:
            y, sr = librosa.load(tmp_path, sr=22050, mono=True)
        finally:
            os.remove(tmp_path)

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr, trim=False)
        bpm = round(float(np.atleast_1d(tempo)[0]), 1)
        duracion = round(float(librosa.get_duration(y=y, sr=sr)), 1)

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
                "p_motor": "cloudrun-librosa-v1"
            },
            timeout=30
        )

        if resp.status_code != 200:
            return jsonify({"error": "fallo guardado en supabase", "detalle": resp.text}), 500

        if resp.text.strip() != "true":
            return jsonify({
                "error": "no se guardo: el tema ya estaba analizado o el hash no existe",
                "hash_archivo": hash_archivo, "bpm": bpm, "duracion_seg": duracion
            }), 409

        return jsonify({"ok": True, "hash_archivo": hash_archivo, "bpm": bpm, "duracion_seg": duracion}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
