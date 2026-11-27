"""
sensibles.py — Encuentra datos personales o sensibles en un texto, sin IA.

Interfaz:
    filtrar(texto, tipos=None) -> (texto_con_etiquetas, {tipo: cantidad})
    tipos_en(texto, tipos=None) -> [tipo]          qué tipos aparecen, en el orden de REGLAS

Cada tipo de dato es una Regla de la lista REGLAS. Para sumar uno nuevo se
agrega una Regla (patrón, y si hace falta una validación); no hay que tocar
filtrar(). El orden importa: va de lo más específico a lo más general, para que
un CUIT no termine tomado por teléfono ni un email por clave. Cada regla corre
sobre el texto que dejaron las anteriores, con las etiquetas ya puestas.

Lo usa el filtro "datos sensibles" de la redacción (generacion/filtros.py).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

ETIQUETAS = {
    "clave": "[CLAVE]", "email": "[EMAIL]", "cuenta": "[CUENTA]", "tarjeta": "[TARJETA]", "cuit": "[CUIT]",
    "cnpj": "[CNPJ]", "cpf": "[CPF]", "dni": "[DNI]", "telefono": "[TELÉFONO]", "monto": "[MONTO]",
}
TIPOS = tuple(ETIQUETAS)


@dataclass(frozen=True)
class Regla:
    tipo: str                                        # una clave de ETIQUETAS
    patron: re.Pattern
    valido: Callable[[re.Match], bool] | None = None  # descarta lo que el patrón toma de más
    grupo: int = 0                                   # qué se oculta: 0 = todo; n = solo ese grupo (el valor
                                                     # que sigue a "clave:", "DNI", "tel.")


# ── Validaciones de números ──────────────────────────────────────────────────

def _digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


def _luhn(num: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(num)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _cuit_valido(num: str) -> bool:
    if len(num) != 11 or num[:2] not in ("20", "23", "24", "27", "30", "33", "34"):
        return False
    resto = sum(int(d) * p for d, p in zip(num[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2), strict=True)) % 11
    verificador = 0 if resto == 0 else 9 if resto == 1 else 11 - resto
    return verificador == int(num[10])


def _cpf_valido(num: str) -> bool:
    if len(num) != 11 or len(set(num)) == 1:
        return False
    for largo in (9, 10):
        suma = sum(int(d) * (largo + 1 - i) for i, d in enumerate(num[:largo]))
        if (suma * 10 % 11) % 10 != int(num[largo]):
            return False
    return True


def _cnpj_valido(num: str) -> bool:
    if len(num) != 14 or len(set(num)) == 1:
        return False
    pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for largo in (12, 13):
        resto = sum(int(d) * p for d, p in zip(num[:largo], pesos[13 - largo:], strict=True)) % 11
        if (0 if resto < 2 else 11 - resto) != int(num[largo]):
            return False
    return True


def _iban_valido(texto: str) -> bool:
    s = re.sub(r"\s", "", texto).upper()
    if not 15 <= len(s) <= 34:
        return False
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def _es_fecha_o_rango(candidato: str) -> bool:
    """15-03-2026, 2026-03-15, 2025-2026, 2025 2026: parecen teléfonos (o tarjetas) y no lo son."""
    grupos = re.split(r"[\s-]+", candidato.strip())
    largos = [len(g) for g in grupos]
    if len(grupos) == 3 and (largos[0] == 4 and largos[1] <= 2 and largos[2] <= 2
                             or largos[0] <= 2 and largos[1] <= 2 and largos[2] in (2, 4)):
        return True
    if re.match(r"(?:19|20)\d\d-\d\d\b", candidato.strip()):   # "2026-27 …": una temporada
        return True
    return all(len(g) == 4 and g[:2] in ("19", "20") for g in grupos)


def _forma_de_tarjeta(candidato: str) -> bool:
    """Pegada, en grupos de 4 (el último puede ser más corto) o 4-6-5 (Amex). "011 15 4567-8901" no."""
    largos = [len(g) for g in re.split(r"[\s-]+", candidato.strip())]
    return len(largos) == 1 or largos == [4, 6, 5] or (all(n == 4 for n in largos[:-1]) and largos[-1] <= 4)


# ── Claves ───────────────────────────────────────────────────────────────────
# "Clave", "secreto" y "pin" también son palabras comunes ("factor clave: el precio",
# "la clave: 2026 será el año", "pin: 1234 rpm"). Después de ellas no se toma una palabra
# sola, un año ni un número con unidad, y detrás de un sustantivo son adjetivos ("factor
# clave: 1500"). "clave=abc", pegado, siempre es una clave.
_AMBIGUAS = ("clave", "secreto", "secreta", "pin")
_NO_SUSTANTIVOS = {"y", "e", "o", "la", "su", "mi", "tu", "sus", "tus", "con", "de", "del", "nueva", "nuevo", "a"}
_UNIDAD = re.compile(r"(?i)\s*(?:rpm|km|kms|cv|hp|nm|kg|kwh?|litros|unidades|piezas|%|°)")
_CLAVE_ETIQUETADA = re.compile(
    r"(?i)\b(contrase[ñn]a|clave|password|passwd|pwd|senha|token|api[ _-]?key|secret[oa]?|pin)\b"
    r"(\s*(?:(?:de|del|da|do)\s+\w+\s*)?(?:[:=]|\s(?:es|is|é)\b:?)\s*)(\S+)")


def _clave_valida(m: re.Match) -> bool:
    palabra, valor = m.group(1).lower(), m.group(3)
    if palabra not in _AMBIGUAS or m.group(2) == "=":
        return True
    if valor.isalpha() or re.fullmatch(r"(?:19|20)\d\d[.,]?", valor) or _UNIDAD.match(m.string, m.end()):
        return False
    antes = re.search(r"(\w+)\s+$", m.string[:m.start()])
    return palabra == "pin" or not antes or antes.group(1).lower() in _NO_SUSTANTIVOS


_TOKENS = re.compile(
    r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"            # OpenAI, Stripe…
    r"|\bpat-[a-z0-9]{2,4}-[a-f0-9-]{20,}"          # HubSpot
    r"|\bnvapi-[A-Za-z0-9_-]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"                          # AWS
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"                  # GitHub
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"                # Slack
    r"|\bAIza[0-9A-Za-z_-]{35}"                       # Google
    r"|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"   # JWT
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/-]{20,}=*"
    # Cadena larga con mayúsculas, minúsculas y números: una clave sin nombre conocido. Un hash
    # hexadecimal (un solo tipo de letra) o una cadena dentro de una URL es un ID, no una clave.
    r"|(?<![/=#?&.-])\b(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{32,}\b(?![/=.-])")

# ── Contacto, cuentas y documentos ───────────────────────────────────────────
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# "juan [at] gmail.com", "juan arroba gmail punto com"
_EMAIL_OFUSCADO = re.compile(r"(?i)[\w.+-]+\s*(?:\[at\]|\(at\)|\[arroba\]|\(arroba\)|\s+arroba\s+)\s*[\w-]+"
                             r"(?:\s*(?:\.|\[dot\]|\(dot\)|\[punto\]|\s+punto\s+)\s*[\w-]+)+")
_CVV = re.compile(r"(?i)\b(cvv2?|cvc2?|c[oó]digo de seguridad)(\s*[:=]?\s*)(\d{3,4})\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")
_CBU = re.compile(r"(?<!\d)\d{22}(?!\d)")
_TARJETA = re.compile(r"(?<![\d+-])\d(?:[ -]?\d){12,18}(?![\d-])")
_CUIT = re.compile(r"(?<![\d.-])(?:20|23|24|27|30|33|34)([-. ]?)\d{8}\1\d(?![\d.-])")
_CNPJ = re.compile(r"(?<![\d./-])\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?![\d./-])")
_CPF = re.compile(r"(?<![\d.-])\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?![\d.-])")
# ponytail: un DNI solo se reconoce con su palabra cerca ("DNI 30.123.456", "documento del titular:
# 30123456"). Un "30.123.456" suelto es igual a un monto o a una cifra de mercado.
_DNI = re.compile(r"(?i)\b(d\.?\s?n\.?\s?i\.?|documento|doc\.|pasaporte|passaporte|passport|rg(?=\s*[:#])|l\.?\s?e\.|l\.?\s?c\.)"
                  r"((?:\s+(?:de|del|da|do|la|el|identidad|identificaci[oó]n|titular|n[º°o.]*|nro\.?|n[uú]mero|n\.º))*"
                  r"\s*[:#]?\s*(?:(?:es|is|é)\s+)?)"
                  r"((?-i:[A-Z]{0,3})\s?\d[\d.\s-]{4,12}\d)")

# ── Teléfonos ────────────────────────────────────────────────────────────────
_TEL = re.compile(r"(?<![\w/.,+])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s-]?)?\d{1,5}(?:[\s-]\d{1,5}){1,5}(?![\w/]|[.,]\d)"
                  r"|\+\d{8,15}\b"
                  r"|(?<![\w/.,+-])(?:0[1-9]\d{9}|[1-9]\d{9,10})(?![\w/-]|[.,]\d)")   # pegado: 1145678901
# Un código o una lista de números no es un teléfono: "SKU 1234-5678-9012", "11 2345 6789 unidades".
_NO_TEL_ANTES = re.compile(r"(?i)\b(?:c[oó]d(?:igo)?|sku|part|parte|pieza|ref|referencia|art|art[ií]culo|oem|modelo|"
                           r"lote|serie|precios?|tabla|rango|ean)\b[\s:#nº°.]*$")
_NO_TEL_DESPUES = re.compile(r"(?i)\s*(?:unidades|uds?\b|piezas|km|kms|cv|hp|nm|kg|litros|autos|veh[ií]culos|%)")
_PALABRA_TEL = r"tel[eé]fonos?|telefone|tel\.?|cel(?:ular)?|m[oó]vil|whats\s?app|wsp|wpp|fone|phone|mobile|fax"
_TEL_ETIQUETADO = re.compile(rf"(?i)\b((?:{_PALABRA_TEL})\s*[:.]?\s*)(\+?[\d\s().-]{{7,22}}\d)")


def _es_telefono(m: re.Match) -> bool:
    candidato, d = m.group(), _digitos(m.group())
    if not 8 <= len(d) <= 15 or _es_fecha_o_rango(candidato):
        return False
    if _NO_TEL_ANTES.search(m.string[max(0, m.start() - 30):m.start()]) or _NO_TEL_DESPUES.match(m.string, m.end()):
        return False
    if re.search(r"[+(]", candidato):
        return True
    grupos = re.split(r"[\s-]+", candidato)
    if len(grupos) == 1:
        return len(d) >= 10
    # Sin + ni característica entre paréntesis, un teléfono termina en 4 cifras ("11 4567-8901") y
    # tiene hasta 11 (13 con el 15 del celular: "011 15 4567-8901"). "1500 2000 3000" es una lista.
    tope = 13 if "15" in grupos[1:-1] else 11
    return len(grupos[-1]) == 4 and len(d) <= tope and (len(d) >= 10 or "-" in candidato)


# ── Montos de contratos ──────────────────────────────────────────────────────
_MONEDA = r"US\$|U\$S|USD|AR\$|ARS|R\$|BRL|EUR|€|\$"
_NUM = r"\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"          # 1.500.000 · 50 000 · 2,65 · 1500
# ponytail: los montos en palabras ("quince mil dólares") no se reconocen.
_MONTO = re.compile(rf"(?i)(?:{_MONEDA})\s?(?:{_NUM})(?:\s?(?:mil(?:lones)?|millones|mm|k|m)\b)?"
                    rf"|\b(?:{_NUM})\s?(?:(?:mil(?:lones)?|millones)\s+)?(?:de\s+)?"
                    rf"(?:USD|U\$S|ARS|BRL|EUR|d[oó]lares|pesos|reales|reais|euros|dollars)(?![\w$])"
                    rf"|\b(?:{_NUM})\s?(?:mil(?:lones)?|millones|MM)\b")
_CONTRATO = re.compile(r"(?i)\b(contrat\w*|acuerdo\w*|acordo\w*|agreement|factur\w*|fatura\w*|invoice\w*|"
                       r"presupuest\w*|or[çc]amento\w*|budget|pag[aoó]\w*|pagamento\w*|payment\w*|abono\w*|"
                       r"fees?|honorari\w*|honor[aá]rios|tarifa\w*|rates?|cotizaci\w*|cota[çc][ãa]o|"
                       r"canon|comisi[oó]n\w*|comiss[ãa]o|commission\w*)")
_FIN_ORACION = re.compile(r"(?<=[.!?;])\s+|\n")


def _en_oracion_de_contrato(m: re.Match) -> bool:
    """Un monto solo es sensible si su oración habla de un contrato, un pago o una tarifa."""
    s = m.string
    ini = max((x.end() for x in _FIN_ORACION.finditer(s, 0, m.start())), default=0)
    fin = next((x.start() for x in _FIN_ORACION.finditer(s, m.end())), len(s))
    return bool(_CONTRATO.search(s[ini:fin]))


# ── La lista ─────────────────────────────────────────────────────────────────

REGLAS: list[Regla] = [
    Regla("clave", _CLAVE_ETIQUETADA, _clave_valida, grupo=3),
    Regla("tarjeta", _CVV, grupo=3),
    Regla("clave", _TOKENS),
    Regla("email", _EMAIL),
    Regla("email", _EMAIL_OFUSCADO),
    Regla("cuenta", _IBAN, lambda m: _iban_valido(m.group())),
    Regla("cuenta", _CBU),
    Regla("tarjeta", _TARJETA, lambda m: 13 <= len(_digitos(m.group())) <= 19 and _luhn(_digitos(m.group()))
          and _forma_de_tarjeta(m.group()) and not _es_fecha_o_rango(m.group())),
    # Con separadores es un CUIT aunque el verificador esté mal tipeado; pegado, solo si cierra.
    Regla("cuit", _CUIT, lambda m: bool(m.group(1)) or _cuit_valido(_digitos(m.group()))),
    Regla("cnpj", _CNPJ, lambda m: "/" in m.group() or _cnpj_valido(_digitos(m.group()))),
    Regla("cpf", _CPF, lambda m: re.search(r"\.\d{3}\.\d{3}-", m.group()) is not None
          or _cpf_valido(_digitos(m.group()))),
    Regla("telefono", _TEL, _es_telefono),
    Regla("dni", _DNI, lambda m: 6 <= len(_digitos(m.group(3))) <= 9, grupo=3),   # "doc. 2024 5000 6000" no
    Regla("telefono", _TEL_ETIQUETADO, lambda m: len(_digitos(m.group(2))) >= 7, grupo=2),
    Regla("monto", _MONTO, _en_oracion_de_contrato),
]


def filtrar(texto: str, tipos: tuple[str, ...] | None = None) -> tuple[str, dict[str, int]]:
    """El texto con lo sensible reemplazado por etiquetas, y cuántos de cada tipo hay. `tipos` limita qué se busca."""
    hallazgos: dict[str, int] = {}

    def reemplazo(m: re.Match, regla: Regla) -> str:
        if regla.valido and not regla.valido(m):
            return m.group()
        hallazgos[regla.tipo] = hallazgos.get(regla.tipo, 0) + 1
        ini, fin = m.start(regla.grupo) - m.start(), m.end(regla.grupo) - m.start()
        return m.group()[:ini] + ETIQUETAS[regla.tipo] + m.group()[fin:]

    texto = texto or ""
    for regla in REGLAS:
        if tipos is None or regla.tipo in tipos:
            texto = regla.patron.sub(lambda m, r=regla: reemplazo(m, r), texto)
    return texto, hallazgos


def tipos_en(texto: str, tipos: tuple[str, ...] | None = None) -> list[str]:
    """Qué tipos de datos sensibles aparecen en el texto, sin repetir."""
    encontrados = filtrar(texto, tipos)[1]
    return [t for t in TIPOS if t in encontrados]
