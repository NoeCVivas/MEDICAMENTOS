from dataclasses import asdict

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from medicamentos import Repositorio, ServicioConsultas

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

print("⏳ Cargando datos desde el CSV o Scraping...")
medicamentos = Repositorio(forzar_refresco=False).obtener()
servicio = ServicioConsultas(medicamentos)
print(f"✅ Servidor listo con {len(medicamentos)} productos cargados.")

BUSCADORES = {
    '2': servicio.por_laboratorio,
    '3': servicio.por_comercial,
    '4': servicio.por_generico,
    '5': servicio.por_accion,
    '6': servicio.por_poblacion,
    '7': servicio.por_categoria,
}


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/api/todos', methods=['GET'])
def obtener_todos():
    return jsonify([asdict(m) for m in servicio.todos()])


@app.route('/api/buscar', methods=['POST'])
def buscar():
    datos = request.json or {}
    opcion = datos.get('opcion')
    query = (datos.get('query') or '').strip()

    if not query:
        return jsonify([])

    fn = BUSCADORES.get(opcion)
    resultados = fn(query) if fn else []
    return jsonify([asdict(m) for m in resultados])


@app.route('/api/imagen', methods=['GET'])
def obtener_imagen():
    nombre = (request.args.get('nombre') or '').strip()
    if not nombre:
        return jsonify({"error": "Falta el nombre"}), 400

    resultados = servicio.por_comercial(nombre)
    if not resultados:
        return jsonify({"error": "Medicamento no encontrado"}), 404

    for med in resultados:
        if med.imagen:
            return jsonify({
                "nombre": med.nombre_comercial,
                "laboratorio": med.laboratorio,
                "imagen": med.imagen,
            })

    return jsonify({"error": "El medicamento no tiene imagen registrada"}), 404


if __name__ == '__main__':
    print("🚀 Iniciando servidor en http://localhost:5000")
    app.run(debug=True, use_reloader=False, port=5000)