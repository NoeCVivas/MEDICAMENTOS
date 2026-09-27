from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dataclasses import asdict

# Importamos tus clases existentes desde medicamentos.py
from medicamentos import Repositorio, ServicioConsultas

# Configuramos Flask para que sirva archivos estáticos (html, css, js) desde la carpeta actual
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# --- CARGA DE DATOS ---
print("⏳ Cargando datos desde el CSV o Scraping...")
repositorio = Repositorio(forzar_refresco=False) 
medicamentos = repositorio.obtener()
servicio = ServicioConsultas(medicamentos)
print(f"✅ Servidor listo con {len(medicamentos)} productos cargados.")

# --- RUTA PARA LA PÁGINA WEB ---
@app.route('/')
def index():
    """Muestra el archivo index.html cuando entrás a localhost:5000"""
    return send_from_directory('.', 'index.html')

# --- RUTAS DE LA API ---

@app.route('/api/todos', methods=['GET'])
def obtener_todos():
    """Devuelve absolutamente todos los medicamentos (Opción 1)."""
    lista = servicio.todos()
    return jsonify([asdict(m) for m in lista])

@app.route('/api/buscar', methods=['POST'])
def buscar():
    """Recibe una opción y un texto, y devuelve los resultados filtrados (Opciones 2 a 7)."""
    datos = request.json
    opcion = datos.get('opcion')
    query = datos.get('query', '').strip()

    if not query:
        return jsonify([])

    if opcion == '2':
        resultados = servicio.por_laboratorio(query)
    elif opcion == '3':
        resultados = servicio.por_comercial(query)
    elif opcion == '4':
        resultados = servicio.por_generico(query)
    elif opcion == '5':
        resultados = servicio.por_accion(query)
    elif opcion == '6':
        resultados = servicio.por_poblacion(query)
    elif opcion == '7':
        resultados = servicio.por_categoria(query)
    else:
        resultados = []

    return jsonify([asdict(m) for m in resultados])

@app.route('/api/imagen', methods=['GET'])
def obtener_imagen():
    """Busca un medicamento por nombre y devuelve los datos de su imagen (Opción 8)."""
    nombre = request.args.get('nombre', '').strip()
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
                "imagen": med.imagen
            })
    
    return jsonify({"error": "El medicamento no tiene imagen registrada"}), 404

if __name__ == '__main__':
    print("🚀 Iniciando servidor en http://localhost:5000")
    app.run(debug=True, use_reloader=False, port=5000)