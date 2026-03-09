import os
import asyncio
import uuid
import edge_tts
from flask import Flask, render_template, request, jsonify, url_for
from werkzeug.utils import secure_filename
import PyPDF2
from docx import Document
import tempfile

app = Flask(__name__)

# Configuración
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "static", "audios")
os.makedirs(AUDIO_DIR, exist_ok=True)

# Extensiones permitidas para subir documentos
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Función para extraer texto de archivos
def extract_text_from_file(filepath, extension):
    text = ""
    if extension == 'txt':
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    elif extension == 'pdf':
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    elif extension == 'docx':
        doc = Document(filepath)
        text = "\n".join([para.text for para in doc.paragraphs])
    return text

# Función para obtener voces de edge-tts
async def fetch_voices():
    return await edge_tts.list_voices()

# Cargar voces al iniciar
try:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    voices_data = loop.run_until_complete(fetch_voices())
    loop.close()
    VOCES = {}
    for v in voices_data:
        locale = v['Locale']
        name_parts = v['ShortName'].split('-')
        friendly_name = name_parts[-1] if len(name_parts) >= 3 else v['ShortName']
        label = f"{locale} - {friendly_name}"
        VOCES[label] = v['ShortName']
except Exception as e:
    print("Error al obtener voces:", e)
    # Voces de respaldo
    VOCES = {
        "Español (MX) - Marina": "es-MX-MarinaNeural",
        "Español (MX) - Gerardo": "es-MX-GerardoNeural",
        "Español (ES) - Álvaro": "es-ES-AlvaroNeural",
        "Inglés (US) - Guy": "en-US-GuyNeural",
    }

async def generar_tts(texto, voz, velocidad, ruta):
    communicate = edge_tts.Communicate(texto, voz, rate=velocidad)
    await communicate.save(ruta)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", voces=VOCES)

@app.route("/upload", methods=["POST"])
def upload_file():
    """
    Recibe un archivo, extrae el texto y lo devuelve en JSON.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No se envió ningún archivo"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nombre de archivo vacío"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Tipo de archivo no permitido. Solo txt, pdf, docx"}), 400

    # Guardar archivo temporalmente
    suffix = file.filename.rsplit('.', 1)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{suffix}") as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        extension = suffix
        text = extract_text_from_file(tmp_path, extension)
        if not text.strip():
            return jsonify({"error": "No se pudo extraer texto del archivo (puede estar vacío o ser escaneado)."}), 400
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": f"Error al procesar archivo: {str(e)}"}), 500
    finally:
        # Eliminar archivo temporal
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.route("/convertir", methods=["POST"])
def convertir():
    try:
        texto = request.form.get("texto", "").strip()
        voz = request.form.get("voz")
        velocidad = request.form.get("velocidad", "+0%")

        if not texto:
            return jsonify({"error": "El texto no puede estar vacío"}), 400

        if voz not in VOCES.values():
            return jsonify({"error": f"La voz '{voz}' no es válida."}), 400

        nombre_archivo = f"{uuid.uuid4()}.mp3"
        ruta_completa = os.path.join(AUDIO_DIR, nombre_archivo)

        # Usar un nuevo event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(generar_tts(texto, voz, velocidad, ruta_completa))
        except Exception as e:
            return jsonify({"error": f"Error al generar audio: {str(e)}"}), 500
        finally:
            loop.close()

        if not os.path.exists(ruta_completa) or os.path.getsize(ruta_completa) == 0:
            return jsonify({"error": "El archivo de audio se generó pero está vacío"}), 500

        audio_url = url_for('static', filename=f'audios/{nombre_archivo}', _external=True)
        return jsonify({"url": audio_url})

    except Exception as e:
        print("❌ Error en /convertir:", str(e))
        return jsonify({"error": f"Error interno: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)