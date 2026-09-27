from __future__ import annotations

import csv
import difflib
import os
import re
import time
import unicodedata
from dataclasses import dataclass, fields as dc_fields
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin

import certifi
import requests
import urllib3
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USAR_WDM = True
except ImportError:
    USAR_WDM = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
URL_ROEMMERS_API = "https://roemmers.com.ar/wp-json/wp/v2/producto"
URL_ROEMMERS_BASE = "https://roemmers.com.ar/producto/"
URL_CASASCO_LISTADO = "https://www.casasco.com.ar/es/productos"
CSV_CACHE = "productos_laboratorios.csv"
FORZAR_REFRESCO = False   # ← poné True una vez para regenerar con imágenes
TIMEOUT = 30

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

CATEGORIAS: dict[str, tuple[str, ...]] = {
    "Cardiología": ("cardio", "corazon", "cardiaco", "hipertension", "antihipertensivo",
                    "anticoagulante", "arritmia", "angina", "vasodilatador",
                    "betabloqueante", "estatin", "colesterol", "triglicerido"),
    "Ginecología": ("ginecolog", "vaginal", "ovulo", "anticonceptiv", "menopausia",
                    "climaterio", "utero", "endometrio", "candida", "tricomonas"),
    "Pediatría": ("pediatric", "infantil", "ninos", "ninas", "bebe", "bebes",
                "junior", "kids", "child", "lactante", "suspension", "gotas",
                "jarabe", "recien nacido"),
    "Analgésico y Antiinflamatorio": ("analgesic", "antiinflamatorio", "dolor",
                                    "corticoide", "antipiretico", "fiebre"),
    "Antibiótico": ("antibiotic", "antibacterial", "antimicrobiano", "infeccion",
                    "penicilina", "cefalosporina", "macrolido", "quinolona"),
    "Gastroenterología": ("gastro", "estomago", "digestiv", "antiacido", "ulcera",
                        "reflujo", "antiemetico", "laxante", "antidiarreico",
                        "hepato", "colon", "intestino"),
    "Dermatología": ("dermatolog", "crema", "unguento", "topico", "piel", "acne",
                    "psoriasis", "micosis", "antifungico"),
    "Neumonología": ("respirator", "asma", "bronquial", "bronco", "pulmonar",
                    "antitusivo", "mucolitico", "expectorante", "inhalador"),
    "Oftalmología": ("oftalm", "ocular", "ojos", "conjuntivitis", "lagrima"),
    "Neurología y Psiquiatría": ("neurolog", "psiquiatr", "antidepresivo",
                                "ansiolitico", "antipsicotico", "epilepsia",
                                "anticonvulsivo", "parkinson", "migrana", "insomnio"),
    "Endocrinología": ("diabetes", "hipoglucemiante", "antidiabetico", "insulina",
                    "tiroides", "tiroideo", "hormona"),
    "Urología": ("urolog", "prostata", "prostatico", "urinari", "diuretico"),
    "Alergología": ("alergi", "antihistaminico", "antialergico", "rinos"),
    "Vitaminas y Suplementos": ("vitamina", "suplemento", "calcio", "hierro",
                                "mineral", "oligoelemento"),
    "Otorrinolaringología": ("otico", "oido", "otitis", "nasal", "garganta",
                            "faringe", "sinusitis"),
}

REGEX_CONCENTRACION = re.compile(r"(\d+[\.,]?\d*\s*(?:MG|G|MCG|UI|ML|%))", re.I)
REGEX_FORMA = re.compile(
    r"(comprimidos?|c[aá]psulas?|jarabe|crema|gel|soluci[oó]n|suspensi[oó]n|"
    r"inyectable|polvo|gotas|[oó]vulos?|supositorios?|aerosol|spray|jalea|sobres?)",
    re.I)

# ---------------------------------------------------------------------------
# UTILIDADES
# ---------------------------------------------------------------------------
def limpiar(texto: Optional[str]) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def normalizar(texto) -> str:
    """Minúsculas + sin acentos. Base de toda búsqueda case-insensitive."""
    t = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def extraer_concentracion(texto: str) -> str:
    m = REGEX_CONCENTRACION.search(texto or "")
    return m.group(1).strip() if m else ""


def inferir_forma(texto: str) -> str:
    m = REGEX_FORMA.search(texto or "")
    return m.group(1).capitalize() if m else ""


def _url_imagen_valida(url: str) -> bool:
    """Descarta URLs que claramente no son imágenes de producto
    (logos, banners, placeholders, redes sociales, imágenes de compartir)."""
    if not url or url.startswith("data:"):
        return False
    low = url.lower()
    ruido = ("logo", "icon", "sprite", "placeholder", "favicon",
            "whatsapp", "facebook", "instagram", "twitter",
            "share", "social", "default-", "no-image", "sin-imagen")
    return not any(x in low for x in ruido)


def extraer_imagen(soup: BeautifulSoup, base_url: str = "") -> str:
    

    def _abs(url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        if base_url and not url.startswith(("http://", "https://", "//")):
            url = urljoin(base_url, url)
        if url.startswith("//"):
            url = "https:" + url
        return url

    # 1) Meta tags
    for prop in ("og:image", "twitter:image"):
        tag = (soup.find("meta", property=prop)
            or soup.find("meta", attrs={"name": prop}))
        if tag and tag.get("content"):
            candidata = _abs(tag["content"])
            if _url_imagen_valida(candidata):
                return candidata

    descartar = ("logo", "icon", "sprite", "placeholder", "banner",
                "favicon", "whatsapp", "facebook", "instagram", "twitter",
                "share", "social", "no-image", "sin-imagen")

    candidatas: list[tuple[int, str]] = []
    for img in soup.select("img"):
        # Priorizar atributos lazy-load reales por sobre src
        src = ""
        for attr in ("data-src", "data-lazy-src", "data-original", "src"):
            v = (img.get(attr) or "").strip()
            if v and not v.startswith("data:"):
                src = v
                break
        if not src:
            continue

        low = src.lower()
        if any(x in low for x in descartar):
            continue

        clases_img = " ".join(img.get("class") or [])
        padre = img.find_parent()
        clases_padre = " ".join(padre.get("class") or []) if padre else ""
        contexto = f"{clases_img} {clases_padre}".lower()

        peso = 0
        if any(k in contexto for k in ("product", "producto",
                                       "field--name-field-imagen",
                                       "field--item", "slide", "galeria")):
            peso = 3
        elif any(k in low for k in ("sites/default/files", "/files/",
                                     "upload", "product")):
            peso = 2
        elif img.get("width") and img.get("width").isdigit() and int(img["width"]) >= 200:
            peso = 1

        candidatas.append((peso, _abs(src)))

    if not candidatas:
        return ""
    candidatas.sort(key=lambda x: -x[0])
    return candidatas[0][1].strip()

# ---------------------------------------------------------------------------
# MODELO
# ---------------------------------------------------------------------------
@dataclass
class Medicamento:
    laboratorio: str = ""
    nombre_comercial: str = ""
    nombre_generico: str = ""
    concentracion: str = ""
    forma_farmaceutica: str = ""
    accion_terapeutica: str = ""
    presentaciones: str = ""
    poblacion: str = ""
    categoria_terapeutica: str = ""
    imagen: str = ""

    @classmethod
    def desde_fila(cls, fila: dict) -> "Medicamento":
        validos = {f.name for f in dc_fields(cls)}
        return cls(**{k: (v or "") for k, v in fila.items() if k in validos})

    def clasificar(self) -> None:
        """Completa poblacion y categoria_terapeutica a partir del texto."""
        texto = normalizar(" ".join((
            self.nombre_comercial, self.nombre_generico, self.accion_terapeutica,
            self.presentaciones, self.forma_farmaceutica,
        )))
        ped = CATEGORIAS["Pediatría"]
        self.poblacion = "Pediátrico" if any(k in texto for k in ped) else "Adultos"
        self.categoria_terapeutica = next(
            (cat for cat, keys in CATEGORIAS.items() if any(k in texto for k in keys)),
            "General")

# ---------------------------------------------------------------------------
# SCRAPERS
# ---------------------------------------------------------------------------
def crear_driver() -> webdriver.Chrome:
    opts = Options()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--window-size=1920,1080", "--lang=es-AR"):
        opts.add_argument(arg)
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    service = Service(ChromeDriverManager().install()) if USAR_WDM else None
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(TIMEOUT)
    return driver


class BaseScraper:

    LAB = ""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._driver: Optional[webdriver.Chrome] = None

    def get(self, url: str) -> Optional[requests.Response]:
        try:
            return self.session.get(url, timeout=TIMEOUT, verify=certifi.where())
        except requests.exceptions.SSLError:
            try:
                return self.session.get(url, timeout=TIMEOUT, verify=False)
            except requests.RequestException:
                return None
        except requests.RequestException:
            return None

    def soup(self, url: str) -> Optional[BeautifulSoup]:
        r = self.get(url)
        if r is None or r.status_code != 200:
            return None
        r.encoding = r.apparent_encoding or r.encoding
        return BeautifulSoup(r.text, "html.parser")

    def soup_selenium(self, url: str, espera_css: str = "img",
                    pausa: float = 0.6) -> Optional[BeautifulSoup]:
        """Carga la URL con Selenium (ejecuta JS) y devuelve el DOM parseado."""
        driver = self.driver()
        try:
            driver.get(url)
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, espera_css)))
            except Exception:
                pass
            # Dar tiempo al lazy-load
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
            time.sleep(pausa)
            return BeautifulSoup(driver.page_source, "html.parser")
        except Exception:
            return None

    def driver(self) -> webdriver.Chrome:
        if self._driver is None:
            print(f"  → Iniciando navegador ({self.LAB})...")
            self._driver = crear_driver()
        return self._driver

    def cerrar(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    def armar(self, **kwargs) -> Medicamento:
        """Crea un Medicamento del laboratorio actual y lo clasifica."""
        med = Medicamento(laboratorio=self.LAB, **kwargs)
        med.clasificar()
        return med

    def parsear_lote(self, items: Iterable, parser: Callable,
                    pausa: float = 0.15) -> list[Medicamento]:
        items = list(items)
        print("  → Visitando fichas...")
        out = []
        for i, item in enumerate(items, 1):
            if i % 40 == 0:
                print(f"     ...{i}/{len(items)}")
            out.append(parser(item))
            time.sleep(pausa)
        return out


class ScraperRoemmers(BaseScraper):

    LAB = "Roemmers"

    def obtener_productos(self) -> list[Medicamento]:
        print("\n" + "=" * 60 + "\n🌐 ROEMMERS\n" + "=" * 60)
        items = self._listar()
        print(f"  → {len(items)} productos detectados.")
        if not items:
            return []
        out = self.parsear_lote(items, self._parsear, pausa=0.2)
        con_pa = sum(1 for m in out if m.nombre_generico)
        con_img = sum(1 for m in out if m.imagen)
        print(f"  ✔ {self.LAB}: {len(out)} productos "
            f"(principio activo: {con_pa}/{len(out)}, imágenes: {con_img}/{len(out)})")
        return out

    def _listar(self) -> list[dict]:
        items = []
        for pagina in range(1, 41):
            url = (f"{URL_ROEMMERS_API}?per_page=100&page={pagina}"
                f"&_fields=id,slug,title")
            print(f"  → API página {pagina}...")
            r = self.get(url)
            if r is None or r.status_code != 200:
                break
            try:
                data = r.json()
            except ValueError:
                break
            if not isinstance(data, list) or not data:
                break
            items += [{"slug": it["slug"], "title": limpiar(it["title"]["rendered"])}
                    for it in data]
            if pagina >= int(r.headers.get("X-WP-TotalPages", "1")):
                break
            time.sleep(0.2)
        return items

    def _parsear(self, item: dict) -> Medicamento:
        url = f"{URL_ROEMMERS_BASE}{item['slug']}/"
        soup = self.soup(url)
        if soup is None:
            return self.armar(nombre_comercial=item["title"])
        imagen = extraer_imagen(soup, base_url=url)
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        texto = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
        med = self._parsear_texto(texto, item["title"])
        med.imagen = imagen
        return med

    def _parsear_texto(self, texto: str, nombre: str) -> Medicamento:
        def extraer(patron: str) -> str:
            m = re.search(patron, texto, re.I)
            return m.group(1).strip()[:500] if m else ""

        principio = extraer(
            r"Principio\s*Activo\s*:?\s*(.+?)(?=\s*(PRESENTACIONES|ACCI[OÓ]N|$))")
        presentaciones = extraer(
            r"PRESENTACIONES\s*:?\s*(.+?)(?=\s*(ACCI[OÓ]N|Principio|$))")
        accion = extraer(
            r"ACCI[OÓ]N\s*(?:TERAP[EÉ]UTICA)?\s*:?\s*(.+?)"
            r"(?=\s*(PRESENTACIONES|Principio\s*Activo|$))")
        return self.armar(
            nombre_comercial=nombre,
            nombre_generico=principio,
            concentracion=extraer_concentracion(principio),
            accion_terapeutica=accion,
            presentaciones=presentaciones,
            forma_farmaceutica=inferir_forma(f"{presentaciones} {principio}"))


class ScraperCasasco(BaseScraper):
    """Listado paginado con Selenium + fichas por requests (con fallback a Selenium)."""
    LAB = "Casasco"

    def obtener_productos(self) -> list[Medicamento]:
        print("\n" + "=" * 60 + "\n🌐 CASASCO\n" + "=" * 60)
        try:
            productos = self._listar()
            print(f"  → {len(productos)} productos detectados.")
            if not productos:
                return []
            out = self.parsear_lote(productos.items(),
                                    lambda kv: self._parsear(*kv), pausa=0.15)
            con_img = sum(1 for m in out if m.imagen)
            print(f"  ✔ {self.LAB}: {len(out)} productos "
                f"(imágenes: {con_img}/{len(out)})")
            return out
        finally:
            self.cerrar()

    def _listar(self) -> dict[str, str]:
        driver = self.driver()
        productos: dict[str, str] = {}
        vacias = 0
        for pagina in range(1, 51):
            print(f"  → Página {pagina}...")
            try:
                driver.get(f"{URL_CASASCO_LISTADO}?page={pagina}")
                WebDriverWait(driver, 15).until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "a[href*='/producto/']")))
            except Exception:
                time.sleep(2)
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            nuevos = 0
            for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/producto/']"):
                href = (a.get_attribute("href") or "").split("#")[0].split("?")[0]
                nombre = limpiar(a.text)
                if ("/producto/" in href and nombre and len(nombre) <= 100
                        and href not in productos):
                    productos[href] = nombre
                    nuevos += 1
            print(f"     {nuevos} nuevos.")
            if nuevos == 0:
                vacias += 1
                if vacias >= 2:
                    break
            else:
                vacias = 0
            time.sleep(0.4)
        return productos

    def _parsear(self, url: str, nombre: str) -> Medicamento:
        # 1) Intento rápido con requests
        soup = self.soup(url)
        imagen = extraer_imagen(soup, base_url=url) if soup else ""

        # 2) Si no hay imagen, reintento con Selenium (el sitio carga JS)
        if not imagen:
            soup_js = self.soup_selenium(url)
            if soup_js is not None:
                soup = soup_js
                imagen = extraer_imagen(soup, base_url=url)

        if soup is None:
            return self.armar(nombre_comercial=nombre)

        d = self._extraer_datos(soup)
        med = self.armar(
            nombre_comercial=nombre,
            nombre_generico=d.get("principio", ""),
            concentracion=extraer_concentracion(d.get("principio", "")),
            accion_terapeutica=d.get("accion", ""),
            presentaciones=d.get("presentaciones", ""),
            forma_farmaceutica=inferir_forma(
                f"{d.get('descripcion', '')} {d.get('presentaciones', '')}"))
        med.imagen = imagen
        return med

    @staticmethod
    def _extraer_datos(soup: BeautifulSoup) -> dict:
        etiquetas = {"principio": "principio activo", "accion": "accion terapeutica",
                    "presentaciones": "presentacion", "descripcion": "descripcion"}
        datos: dict = {}
        for block in soup.select("div.product-block"):
            label = block.select_one("h6.spec-label")
            value = block.select_one(".field--item")
            if label and value:
                campo = normalizar(label.get_text())
                for clave, etiqueta in etiquetas.items():
                    if etiqueta in campo:
                        datos[clave] = limpiar(value.get_text())
        if not datos.get("principio"):
            for tag in soup.find_all(["h2", "h3", "h4", "h5", "h6", "strong"]):
                etiqueta = normalizar(tag.get_text())
                sib = tag.find_next_sibling()
                if not sib:
                    continue
                if "principio activo" in etiqueta:
                    datos["principio"] = limpiar(sib.get_text())
                elif "accion terapeutica" in etiqueta:
                    datos["accion"] = limpiar(sib.get_text())
        return datos

# ---------------------------------------------------------------------------
# REPOSITORIO
# ---------------------------------------------------------------------------
class Repositorio:

    def __init__(self, forzar_refresco: bool = FORZAR_REFRESCO) -> None:
        self._forzar = forzar_refresco

    def obtener(self) -> list[Medicamento]:
        if not self._forzar:
            filas = self._cargar_csv()
            if filas:
                return [Medicamento.desde_fila(f) for f in filas]
        print(f"\n{'=' * 60}\nDESCARGANDO PRODUCTOS\n{'=' * 60}")
        medicamentos = (ScraperRoemmers().obtener_productos()
                        + ScraperCasasco().obtener_productos())
        if not medicamentos:
            print("❌ No se pudieron obtener productos.")
            return []
        print(f"\n✔ Total de productos: {len(medicamentos)}")
        self._guardar_csv(medicamentos)
        return medicamentos

    @staticmethod
    def _cargar_csv() -> list[dict]:
        if not os.path.exists(CSV_CACHE):
            return []
        try:
            with open(CSV_CACHE, encoding="utf-8") as f:
                filas = list(csv.DictReader(f))
            print(f"✔ CSV en caché: {CSV_CACHE} ({len(filas)} registros)")
            return filas
        except Exception as e:
            print(f"⚠ Error leyendo {CSV_CACHE}: {e}")
            return []

    @staticmethod
    def _guardar_csv(medicamentos: list[Medicamento]) -> None:
        with open(CSV_CACHE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(medicamentos[0].__dict__))
            w.writeheader()
            w.writerows(m.__dict__ for m in medicamentos)
        print(f"✔ Guardado en {CSV_CACHE}")

# SERVICIO DE CONSULTAS
class ServicioConsultas:
    """Búsquedas case/acento-insensibles + filtros por categoría."""

    def __init__(self, medicamentos: list[Medicamento]) -> None:
        self._meds = medicamentos

    def todos(self) -> list[Medicamento]:
        return self._meds

    def _filtrar(self, texto: str, *campos: str) -> list[Medicamento]:
        if not texto:
            return []
        patron = re.compile(re.escape(normalizar(texto)), re.I)
        return [m for m in self._meds
                if any(patron.search(normalizar(getattr(m, c, ""))) for c in campos)]

    def por_laboratorio(self, t): return self._filtrar(t, "laboratorio")
    def por_comercial(self, t):   return self._filtrar(t, "nombre_comercial")
    def por_generico(self, t):    return self._filtrar(t, "nombre_generico")
    def por_accion(self, t):      return self._filtrar(t, "accion_terapeutica")
    def por_poblacion(self, t):   return self._filtrar(t, "poblacion")
    def por_categoria(self, t):   return self._filtrar(t, "categoria_terapeutica")

    def laboratorios(self) -> list[str]:
        return sorted({m.laboratorio for m in self._meds if m.laboratorio})

    def categorias(self) -> list[str]:
        return sorted({m.categoria_terapeutica for m in self._meds
                    if m.categoria_terapeutica})

    def conteo_por_categoria(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for m in self._meds:
            c = m.categoria_terapeutica
            if c:
                conteo[c] = conteo.get(c, 0) + 1
        return dict(sorted(conteo.items(), key=lambda x: -x[1]))

    def sugerir_genericos(self, texto: str, n: int = 5) -> list[str]:
        mapa = {normalizar(m.nombre_generico): m.nombre_generico
                for m in self._meds if m.nombre_generico}
        return [mapa[k] for k in difflib.get_close_matches(
            normalizar(texto), list(mapa), n=n, cutoff=0.5)]

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class CLI:
    def __init__(self, servicio: ServicioConsultas) -> None:
        self._s = servicio
        self._opciones: dict[str, tuple[str, Callable[[], None]]] = {
            "1": ("Mostrar todos los productos", self._todos),
            "2": ("Buscar por laboratorio", self._por_laboratorio),
            "3": ("Buscar por nombre comercial", self._por_comercial),
            "4": ("Buscar por principio activo", self._por_generico),
            "5": ("Buscar por acción terapéutica", self._por_accion),
            "6": ("Filtrar por población (pediátrico/adultos)", self._por_poblacion),
            "7": ("🩺 Filtrar por categoría (cardiológicos, ginecológicos, etc.)",
                self._por_categoria),
            "8": ("🖼️  Bajar imagen del medicamento (buscar por nombre)",
                self._bajar_imagen),
            "9": ("Salir", self._salir),
        }

    def ejecutar(self) -> None:
        while True:
            self._menu()
            op = input("Elegí una opción: ").strip()
            if op not in self._opciones:
                print("Opción inválida.")
                continue
            self._opciones[op][1]()
            if op == "9":
                break

    def _menu(self) -> None:
        print("\n" + "=" * 60)
        print("💊 PRODUCTOS DE LABORATORIOS")
        print("=" * 60)
        for k, (desc, _) in self._opciones.items():
            print(f"{k}. {desc}")
        print("=" * 60)

    def _mostrar(self, lista: list[Medicamento], criterio: str) -> None:
        if not lista:
            print(f"\n❌ Sin resultados para {criterio}.")
            return
        print(f"\n🔍 {len(lista)} resultados para {criterio}:\n")
        for m in lista:
            partes = [f"[{m.laboratorio}] {m.nombre_comercial}"]
            if m.nombre_generico:
                partes.append(f"({m.nombre_generico[:60]})")
            etiquetas = [x for x in (m.categoria_terapeutica, m.poblacion) if x]
            if etiquetas:
                partes.append("— " + " / ".join(etiquetas))
            print("  • " + " ".join(partes))

    def _pedir(self, prompt: str, fn: Callable, criterio: str) -> None:
        t = input(prompt).strip()
        self._mostrar(fn(t), f"{criterio} '{t}'")

    def _todos(self):
        self._mostrar(self._s.todos(), "todos los productos")

    def _por_laboratorio(self):
        print(f"Laboratorios: {', '.join(self._s.laboratorios())}")
        self._pedir("Nombre del laboratorio: ",
                    self._s.por_laboratorio, "laboratorio")

    def _por_comercial(self):
        self._pedir("Nombre comercial: ", self._s.por_comercial, "comercial")

    def _por_generico(self):
        t = input("Principio activo (ej: ibuprofeno): ").strip()
        res = self._s.por_generico(t)
        if not res:
            sugerencias = self._s.sugerir_genericos(t)
            if sugerencias:
                print(f"\n❌ No se encontró '{t}'. ¿Quisiste decir?")
                for s in sugerencias:
                    print(f"   • {s[:80]}")
                return
        self._mostrar(res, f"principio '{t}'")

    def _por_accion(self):
        self._pedir("Acción terapéutica (ej: analgésico): ",
                    self._s.por_accion, "acción")

    def _por_poblacion(self):
        print("Opciones: 'pediatrico' o 'adultos'")
        t = input("Población [pediatrico]: ").strip() or "pediatrico"
        self._mostrar(self._s.por_poblacion(t), f"población '{t}'")

    def _por_categoria(self):
        categorias = self._s.categorias()
        if not categorias:
            print("\n⚠ No hay categorías clasificadas.")
            return
        print("\nCategorías disponibles:")
        for i, c in enumerate(categorias, 1):
            print(f"  {i:>2}. {c}")
        print("\nPodés escribir el nombre (parcial) o el número de la lista.")
        t = input("Categoría: ").strip()
        if not t:
            return
        if t.isdigit() and 1 <= int(t) <= len(categorias):
            t = categorias[int(t) - 1]
        self._mostrar(self._s.por_categoria(t), f"categoría '{t}'")

    # ------------------------------------------------------------------
    # OPCIÓN 8: bajar imagen del medicamento por nombre
    # ------------------------------------------------------------------
    def _bajar_imagen(self):
        t = input("Nombre del medicamento: ").strip()
        if not t:
            return
        resultados = self._s.por_comercial(t)
        if not resultados:
            print(f"\n❌ No se encontró '{t}'.")
            return

        if len(resultados) > 1:
            print(f"\n🔍 {len(resultados)} coincidencias:")
            for i, m in enumerate(resultados, 1):
                print(f"  {i:>2}. [{m.laboratorio}] {m.nombre_comercial}")
            sel = input("\nElegí un número (Enter = primera): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(resultados):
                med = resultados[int(sel) - 1]
            else:
                med = resultados[0]
        else:
            med = resultados[0]

        if not med.imagen:
            print(f"\n⚠ '{med.nombre_comercial}' ({med.laboratorio}) "
                f"no tiene imagen registrada.")
            print("   Probá con FORZAR_REFRESCO = True para regenerar el CSV.")
            return

        # Red de seguridad: normalizar por si el CSV guardó una URL relativa
        url_imagen = med.imagen
        if not url_imagen.startswith(("http://", "https://")):
            if med.laboratorio == "Casasco":
                url_imagen = urljoin("https://www.casasco.com.ar/", url_imagen)
            elif med.laboratorio == "Roemmers":
                url_imagen = urljoin("https://roemmers.com.ar/", url_imagen)

        print(f"\n🖼️  {med.nombre_comercial} [{med.laboratorio}]")
        print(f"   URL: {url_imagen}")

        try:
            r = requests.get(url_imagen, timeout=TIMEOUT,
                            verify=certifi.where(), headers=HEADERS)
            if r.status_code != 200:
                print(f"   ❌ Error HTTP {r.status_code}")
                return
            ext = os.path.splitext(url_imagen.split("?")[0])[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"
            base = re.sub(r"[^\w\-]+", "_",
                        f"{med.laboratorio}_{med.nombre_comercial}").strip("_")
            nombre_archivo = f"{base}{ext}"
            with open(nombre_archivo, "wb") as f:
                f.write(r.content)
            print(f"   ✔ Imagen guardada: {nombre_archivo}")
        except requests.RequestException as e:
            print(f"   ❌ Error al descargar: {e}")
        except OSError as e:
            print(f"   ❌ Error al escribir el archivo: {e}")

    def _salir(self):
        print("👋 Saliendo...")

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    medicamentos = Repositorio(forzar_refresco=FORZAR_REFRESCO).obtener()
    print(f"\nDatos cargados → productos: {len(medicamentos)}")
    if not medicamentos:
        print("❌ No hay datos disponibles.")
        return
    CLI(ServicioConsultas(medicamentos)).ejecutar()


if __name__ == "__main__":
    main()