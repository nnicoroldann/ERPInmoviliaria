"""
ocr_boletas.py

Intenta leer automáticamente el monto y la fecha de vencimiento de una
boleta de gas o agua que el inquilino sube desde su portal.

Es "best effort": las boletas de EPEC y Ecogas no tienen un formato
único ni estable, así que esto es una ayuda para no tener que tipear
todo a mano, NUNCA una fuente de verdad. El router siempre le muestra
estos valores al inquilino en un formulario editable antes de guardar
nada - si no se pudo adivinar algo, ese campo queda vacío para
completarlo a mano.

Requiere, además de las librerías de Python (pdfplumber, pytesseract,
pdf2image, Pillow), dos programas instalados en el sistema operativo
(no se instalan con pip):

    brew install tesseract poppler

- tesseract: el motor de OCR en sí (lee texto de una imagen).
- poppler: lo usa pdf2image para convertir páginas de un PDF a imagen,
  necesario solo si el PDF es una boleta escaneada (sin texto real
  adentro, como una foto pegada en un PDF).

Si alguna de estas piezas no está instalada, las funciones de acá
devuelven texto vacío en vez de romper la página: simplemente el
inquilino va a tener que completar los campos a mano.
"""

import re
from datetime import date, datetime

MAX_PAGINAS_OCR = 3  # no vale la pena leer boletas de más de 3 páginas


def extraer_texto(ruta: str, content_type: str) -> str:
    """Devuelve todo el texto que se pudo sacar del archivo. Si no se
    pudo leer nada (falta una librería, el archivo está roto, etc.),
    devuelve "" en vez de lanzar una excepción."""
    try:
        if content_type == "application/pdf":
            texto = _texto_de_pdf(ruta)
            if len(texto.strip()) >= 30:
                return texto
            # Muy poco texto: probablemente es un PDF escaneado (una
            # foto metida adentro de un PDF, sin capa de texto real).
            return _ocr_de_pdf_escaneado(ruta)
        return _ocr_de_imagen(ruta)
    except Exception:
        return ""


def _texto_de_pdf(ruta: str) -> str:
    import pdfplumber

    partes = []
    with pdfplumber.open(ruta) as pdf:
        for pagina in pdf.pages[:MAX_PAGINAS_OCR]:
            partes.append(pagina.extract_text() or "")
    return "\n".join(partes)


def _ocr_de_pdf_escaneado(ruta: str) -> str:
    from pdf2image import convert_from_path

    imagenes = convert_from_path(ruta, dpi=200, first_page=1, last_page=MAX_PAGINAS_OCR)
    partes = [_texto_de_imagen_pil(img) for img in imagenes]
    return "\n".join(partes)


def _ocr_de_imagen(ruta: str) -> str:
    from PIL import Image

    with Image.open(ruta) as img:
        return _texto_de_imagen_pil(img)


def _texto_de_imagen_pil(imagen) -> str:
    import pytesseract

    return pytesseract.image_to_string(imagen, lang="spa+eng")


# ---------------------------------------------------------------------
# Heurísticas para adivinar monto y vencimiento dentro del texto leído.
# ---------------------------------------------------------------------

_PALABRAS_MONTO = ("total", "importe", "a pagar", "monto")
_PALABRAS_VENCIMIENTO = ("vencimiento", "vence")

_RE_MONTO = re.compile(r"\$?\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+[.,]\d{2})")
_RE_FECHA = re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})")


def _a_float(texto_monto: str) -> float | None:
    """'12.345,67' o '12345,67' o '12345.67' -> 12345.67"""
    texto_monto = texto_monto.strip()
    if "," in texto_monto:
        texto_monto = texto_monto.replace(".", "").replace(",", ".")
    try:
        return round(float(texto_monto), 2)
    except ValueError:
        return None


def _a_fecha(dia: str, mes: str, anio: str) -> date | None:
    try:
        d, m = int(dia), int(mes)
        a = int(anio)
        if a < 100:
            a += 2000
        return date(a, m, d)
    except ValueError:
        return None


def adivinar_campos(texto: str) -> dict:
    """Busca, línea por línea, un monto cerca de palabras como "total"
    o "a pagar", y una fecha cerca de "vencimiento". Devuelve
    {"monto": float | None, "vencimiento": date | None}."""
    resultado = {"monto": None, "vencimiento": None}
    if not texto:
        return resultado

    lineas = texto.splitlines()

    for linea in lineas:
        linea_baja = linea.lower()
        if resultado["monto"] is None and any(p in linea_baja for p in _PALABRAS_MONTO):
            m = _RE_MONTO.search(linea)
            if m:
                resultado["monto"] = _a_float(m.group(1))

        if resultado["vencimiento"] is None and any(p in linea_baja for p in _PALABRAS_VENCIMIENTO):
            f = _RE_FECHA.search(linea)
            if f:
                resultado["vencimiento"] = _a_fecha(*f.groups())

    return resultado
