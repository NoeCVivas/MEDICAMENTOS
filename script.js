document.addEventListener('DOMContentLoaded', () => {
    const buttons = document.querySelectorAll('.query-btn');
    const resultadosDiv = document.getElementById('resultados');
    const consultaNumSpan = document.getElementById('consulta-num');
    const API_URL = 'http://localhost:5000/api';

    const modalOverlay = document.getElementById('custom-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalMessage = document.getElementById('modal-message');
    const modalInput = document.getElementById('modal-input');
    const modalCancel = document.getElementById('modal-cancel');
    const modalAccept = document.getElementById('modal-accept');

    const nombresConsultas = {
        "1": "Mostrar todos",
        "2": "Por Laboratorio",
        "3": "Por Nombre Comercial",
        "4": "Por Principio Activo",
        "5": "Por Acción Terapéutica",
        "6": "Por Población",
        "7": "Por Categoría",
        "8": "Bajar Imagen",
        "9": "Borrar Pantalla",
        "0": "Salir"
    };

    function pedirDatoModal(titulo, mensaje) {
        return new Promise((resolve) => {
            modalTitle.textContent = titulo;
            modalMessage.textContent = mensaje;
            modalInput.value = '';
            modalOverlay.classList.add('active');
            modalInput.focus();

            const cerrarModal = (valor) => {
                modalOverlay.classList.remove('active');
                modalAccept.removeEventListener('click', onAccept);
                modalCancel.removeEventListener('click', onCancel);
                modalInput.removeEventListener('keypress', onKeyPress);
                resolve(valor);
            };

            const onAccept = () => cerrarModal(modalInput.value.trim());
            const onCancel = () => cerrarModal(null);
            const onKeyPress = (e) => {
                if (e.key === 'Enter') onAccept();
            };

            modalAccept.addEventListener('click', onAccept);
            modalCancel.addEventListener('click', onCancel);
            modalInput.addEventListener('keypress', onKeyPress);
        });
    }

    function ejecutarConsulta(queryId) {
        if (!queryId) return;

        consultaNumSpan.textContent =
            queryId + " (" + (nombresConsultas[queryId] || "Consulta") + ")";

        switch (queryId) {
            case "1": mostrarTodos(); break;
            case "2": buscarConModal("2", "Buscar por Laboratorio", "Ingrese el laboratorio (Roemmers / Casasco):"); break;
            case "3": buscarConModal("3", "Buscar por Nombre Comercial", "Ingrese el nombre comercial:"); break;
            case "4": buscarConModal("4", "Buscar por Principio Activo", "Ingrese el principio activo:"); break;
            case "5": buscarConModal("5", "Buscar por Acción Terapéutica", "Ingrese la acción terapéutica:"); break;
            case "6": buscarConModal("6", "Filtrar por Población", "Ingrese la población (Pediátrico / Adultos):"); break;
            case "7": buscarConModal("7", "Filtrar por Categoría", "Ingrese la categoría (ej: Cardiología, Antibiótico):"); break;
            case "8": bajarImagen(); break;
            case "9": borrarPantalla(); break;
            case "0": salir(); break;
            default: break;
        }
    }

    buttons.forEach(button => {
        button.addEventListener('click', (e) => {
            const queryId = e.currentTarget.getAttribute('data-query');
            ejecutarConsulta(queryId);
        });
    });

    const btnBorrar = document.getElementById('btn-borrar');
    if (btnBorrar && !btnBorrar.getAttribute('data-query')) {
        btnBorrar.addEventListener('click', () => ejecutarConsulta("9"));
    }

    const btnSalir = document.getElementById('btn-salir');
    if (btnSalir && !btnSalir.getAttribute('data-query')) {
        btnSalir.addEventListener('click', () => ejecutarConsulta("0"));
    }

    function mostrarCargando() {
        resultadosDiv.innerHTML =
            `<p class="placeholder-text">Consultando a la base de datos...</p>`;
    }

    function mostrarError(mensaje) {
        resultadosDiv.innerHTML =
            `<p class="placeholder-text" style="color: #b91c1c;">❌ ${mensaje}</p>`;
    }

    function renderizarTabla(datos) {
        if (!datos || datos.length === 0) {
            resultadosDiv.innerHTML =
                `<p class="placeholder-text">No se encontraron resultados.</p>`;
            return;
        }

        let html = `<table>
            <thead>
                <tr>
                    <th>Laboratorio</th>
                    <th>Nombre Comercial</th>
                    <th>Principio Activo</th>
                    <th>Concentración</th>
                    <th>Acción Terapéutica</th>
                </tr>
            </thead>
            <tbody>`;

        datos.forEach(med => {
            html += `<tr>
                <td>${med.laboratorio || '-'}</td>
                <td><strong>${med.nombre_comercial || '-'}</strong></td>
                <td>${med.nombre_generico || '-'}</td>
                <td>${med.concentracion || '-'}</td>
                <td>${med.accion_terapeutica || '-'}</td>
            </tr>`;
        });

        html += `</tbody></table>`;
        resultadosDiv.innerHTML = html;
    }

    async function mostrarTodos() {
        mostrarCargando();
        try {
            const response = await fetch(`${API_URL}/todos`);
            if (!response.ok) throw new Error("Error en el servidor");
            const data = await response.json();
            renderizarTabla(data);
        } catch (error) {
            mostrarError("No se pudo conectar con el servidor Python. ¿Está corriendo app.py?");
        }
    }

    async function buscarConModal(opcion, titulo, mensaje) {
        const query = await pedirDatoModal(titulo, mensaje);
        if (!query) return;

        mostrarCargando();
        try {
            const response = await fetch(`${API_URL}/buscar`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ opcion: opcion, query: query })
            });
            if (!response.ok) throw new Error("Error en el servidor");
            const data = await response.json();
            renderizarTabla(data);
        } catch (error) {
            mostrarError("Error al realizar la búsqueda. Verifique la consola de Python.");
        }
    }

    async function bajarImagen() {
        const nombre = await pedirDatoModal("Buscar Imagen", "Ingrese el nombre del medicamento:");
        if (!nombre) return;

        mostrarCargando();
        try {
            const response = await fetch(`${API_URL}/imagen?nombre=${encodeURIComponent(nombre)}`);

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || "Medicamento no encontrado");
            }

            const data = await response.json();

            resultadosDiv.innerHTML = `
                <div style="text-align: center; padding: 20px;">
                    <h3 style="color: #0C3B45; margin-bottom: 5px;">${data.nombre}</h3>
                    <p style="color: #20666B; font-size: 0.9rem; margin-bottom: 20px;">[${data.laboratorio}]</p>
                    <img src="${data.imagen}" alt="${data.nombre}" style="max-width: 250px; border-radius: 8px; border: 1px solid #88C9C4; box-shadow: 0 4px 6px rgba(12, 59, 69, 0.08);">
                    <br>
                    <a href="${data.imagen}" target="_blank" style="display: inline-block; margin-top: 20px; padding: 10px 20px; background: #20666B; color: white; text-decoration: none; border-radius: 6px; font-size: 0.9rem;">🔗 Abrir Imagen Original</a>
                </div>
            `;
        } catch (error) {
            mostrarError(error.message);
        }
    }

    function borrarPantalla() {
        resultadosDiv.innerHTML =
            `<p class="placeholder-text">🧹 Pantalla borrada. Listo para una nueva consulta.</p>`;
        consultaNumSpan.textContent = "-";
    }

    function salir() {
        resultadosDiv.innerHTML =
            `<p class="placeholder-text">👋 Saliendo del sistema... Puede cerrar la pestaña.</p>`;
        consultaNumSpan.textContent = "-";
    }
});