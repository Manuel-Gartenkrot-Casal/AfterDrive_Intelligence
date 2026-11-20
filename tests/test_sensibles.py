"""Tests del detector de datos sensibles (sensibles.py) con casos reales, positivos y negativos."""

import re

import pytest

from afterdrive import sensibles

# Token falso con el formato de HubSpot, armado en dos partes: escrito entero, la protección de secretos
# de GitHub lo toma por una clave real y rechaza el push.
TOKEN_HUBSPOT_FALSO = "pat-na1-" + "1b2c3d4e-5f60-7182-93a4-b5c6d7e8f901"


@pytest.mark.parametrize("texto, tipo, original", [
    # Emails
    ("Escribile a compras@repuestosdelsur.com.ar por el pedido", "email", "compras@repuestosdelsur.com.ar"),
    ("Contacto: juan.perez+ventas@gmail.com", "email", "juan.perez+ventas@gmail.com"),
    ("Escribir a juan [at] gmail.com", "email", "juan [at] gmail.com"),
    ("Escribir a juan arroba gmail punto com", "email", "juan arroba gmail punto com"),
    # Teléfonos de Argentina, Brasil e internacionales
    ("Llamar al +54 9 11 4567-8901 antes del jueves", "telefono", "+54 9 11 4567-8901"),
    ("Ana, celular +54 9 351 456-7890", "telefono", "+54 9 351 456-7890"),
    ("Oficina: (011) 4567-8901, de 9 a 18", "telefono", "(011) 4567-8901"),
    ("El celu del gerente es 15-4567-8901", "telefono", "15-4567-8901"),
    ("Atiende en el 11 4567 8901", "telefono", "11 4567 8901"),
    ("WhatsApp: 1145678901", "telefono", "1145678901"),
    ("Llamame al 1155551234", "telefono", "1155551234"),
    ("Ligue para (11) 98765-4321 na segunda", "telefono", "(11) 98765-4321"),
    ("Escritório em SP: +55 11 98765-4321", "telefono", "+55 11 98765-4321"),
    ("Call us at +1 415 555 0132", "telefono", "+1 415 555 0132"),
    ("Tel. 4567 8901", "telefono", "4567 8901"),
    ("Celu viejo: 011 15 4567-8901", "telefono", "011 15 4567-8901"),
    ("Atención: 0800 333 1234", "telefono", "0800 333 1234"),
    ("Token interno Xk9pQ2mZ7vB4nL8wR1tY6uE3sD5fG0hJ en el portal", "clave", "Xk9pQ2mZ7vB4nL8wR1tY6uE3sD5fG0hJ"),
    # Documentos
    ("Razón social ACME SA, CUIT 30-71234567-1", "cuit", "30-71234567-1"),
    ("CUIL 20301234563 del titular", "cuit", "20301234563"),
    ("CUIT 27.24567890.3", "cuit", "27.24567890.3"),
    ("Titular: Juan Pérez, DNI 30.123.456", "dni", "30.123.456"),
    ("D.N.I. N° 30123456", "dni", "30123456"),
    ("documento: 18 456 789", "dni", "18 456 789"),
    ("DNI del titular: 30123456", "dni", "30123456"),
    ("mi documento de identidad es 30123456", "dni", "30123456"),
    ("su DNI es 30.123.456", "dni", "30.123.456"),
    ("Pasaporte AAB123456 vence en marzo", "dni", "AAB123456"),
    ("RG: 12.345.678-9", "dni", "12.345.678-9"),
    ("Responsável: CPF 529.982.247-25", "cpf", "529.982.247-25"),
    ("CPF 52998224725", "cpf", "52998224725"),
    ("Empresa CNPJ 11.222.333/0001-81", "cnpj", "11.222.333/0001-81"),
    # Tarjetas y cuentas
    ("Pagan con la Visa 4111 1111 1111 1111", "tarjeta", "4111 1111 1111 1111"),
    ("Tarjeta 5500-0000-0000-0004 vto 12/27", "tarjeta", "5500-0000-0000-0004"),
    ("CVV 123", "tarjeta", "123"),
    ("Transferir al CBU 0170099220000067797370", "cuenta", "0170099220000067797370"),
    ("IBAN ES9121000418450200051332", "cuenta", "ES9121000418450200051332"),
    # Claves y tokens
    ("Usuario: compras / Clave: Hunter2!", "clave", "Hunter2!"),
    ("Usuario y clave: 123456", "clave", "123456"),
    ("La contraseña: mariposa", "clave", "mariposa"),
    ("la contraseña es Hunter2", "clave", "Hunter2"),
    ("password is hunter2", "clave", "hunter2"),
    ("password=Prov2026# para el portal", "clave", "Prov2026#"),
    ("clave=abc", "clave", "abc"),
    ("el pin es 1234", "clave", "1234"),
    ("Senha: abc123", "clave", "abc123"),
    ("API key del CRM: sk-proj-a8F3kd92LmQp0zX7vB1n", "clave", "sk-proj-a8F3kd92LmQp0zX7vB1n"),
    (f"token {TOKEN_HUBSPOT_FALSO}", "clave", TOKEN_HUBSPOT_FALSO),
    ("Header: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcDEF123456", "clave",
     "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcDEF123456"),
    ("AWS AKIAIOSFODNN7EXAMPLE en el .env", "clave", "AKIAIOSFODNN7EXAMPLE"),
    # Montos de contratos (con la palabra en la oración)
    ("El contrato anual es por $ 1.500.000 más IVA.", "monto", "$ 1.500.000"),
    ("Fee mensual: USD 2.500", "monto", "USD 2.500"),
    ("Firmaron un acuerdo de 25 millones de pesos con la terminal.", "monto", "25 millones de pesos"),
    ("O contrato prevê R$ 80.000 por ano.", "monto", "R$ 80.000"),
    ("The agreement is worth US$ 120k a year.", "monto", "US$ 120k"),
    ("Contrato por 50.000 USD", "monto", "50.000 USD"),
    ("Factura 1500 USD", "monto", "1500 USD"),
    ("Contrato: 500 U$S", "monto", "500 U$S"),
    ("contrato por 50 mil USD", "monto", "50 mil USD"),
    ("contrato de 1.500.000 de pesos", "monto", "1.500.000 de pesos"),
    ("contrato por 50 000 USD", "monto", "50 000 USD"),
    ("El contrato asciende a 2 millones", "monto", "2 millones"),
    ("Pagó $5.000.000", "monto", "$5.000.000"),
])
def test_detecta_datos_sensibles(texto, tipo, original):
    filtrado, hallazgos = sensibles.filtrar(texto)
    # El dato entero, no un pedazo: "+54 9" no puede quedar a la vista.
    assert filtrado == texto.replace(original, sensibles.ETIQUETAS[tipo])
    assert hallazgos == {tipo: 1}


@pytest.mark.parametrize("texto", [
    "El mercado de autopartes creció 12% en 2026.",
    "AAPEX 2026 se hace del 4 al 6 de noviembre en Las Vegas.",
    "La feria es el 15/03/2026 y la anterior fue el 15-03-2025.",
    "Temporada 2025-2026 y temporada 2025 2026.",
    "El mercado global, estimado en US$ 2,65 billones, crece.",
    "Hay 45.000.000 de vehículos en circulación y 1.500.000 talleres.",
    "Filtro de aceite W 712/75 y pastillas código 0 986 494 xxx.",
    "Notas de 500 a 700 palabras, o de 1000 1400 palabras.",
    "Un factor clave: el precio. El punto clave: la logística.",
    "El precio de lista es $ 15.000 por unidad.",
    "Visitá https://repuestosdelsur.com.ar/catalogo-2026 para ver el catálogo.",
    "Stand 12-34, pabellón 3.",
    "Ruta 9 km 1234, Córdoba, CP 5000.",
    "La RG 4567 de AFIP cambió el régimen.",
    # Códigos de repuestos y listas de números que parecían teléfonos o tarjetas
    "Código 7700 1234 5678",
    "SKU 1234-5678-9012",
    "Toyota 04152 31090",
    "Part 12345-67890",
    "Precio 1500 2000 2500",
    "Tabla: 100 200 300 400 500",
    "Rango 15 20 25 30 35 40",
    "Se vendieron 11 2345 6789 unidades",
    "Año 2023 2024 2025 2026",
    "Factor clave: 1500 unidades",
    "Bosch 0986494123 y EAN 7791234567890",
    "Motor 2.8 TDI 204 CV 500 Nm, aceite 5W-30, VIN 8AJFB3CD1J1234567.",
    "La página 12 del catálogo",
    # Casos de la segunda revisión: texto típico de una nota
    "Ford Ranger 2.2 TDI 4x4 3000 4000 5000",
    "El stock fue 1500 2000 3000",
    "Entre 1000-2000-3000 pesos",
    "doc. 2024 5000 6000",
    "Passport 2026-27 1234",
    "La clave: 2026 será el año del eléctrico.",
    "la clave es 2026 para el sector",
    "factor clave = 15",
    "Pin: 1234 rpm",
    "[fuente](https://site.com/p/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08)",
    "ID de producto a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8",
])
def test_no_toca_datos_comunes_del_rubro(texto):
    assert sensibles.filtrar(texto) == (texto, {})


def test_cuenta_cada_tipo_y_dice_cuales_hay():
    texto = "Mail: a@b.com y c@d.com. Tel: +54 11 4567-8901. Contrato por USD 10.000."
    filtrado, hallazgos = sensibles.filtrar(texto)
    assert hallazgos == {"email": 2, "telefono": 1, "monto": 1}
    assert filtrado == "Mail: [EMAIL] y [EMAIL]. Tel: [TELÉFONO]. Contrato por [MONTO]."
    assert sensibles.tipos_en(texto) == ["email", "telefono", "monto"]
    assert sensibles.tipos_en(texto, tipos=("email",)) == ["email"]


def test_sumar_una_regla_no_toca_filtrar(monkeypatch):
    patente = sensibles.Regla("patente", re.compile(r"\b[A-Z]{2}\d{3}[A-Z]{2}\b"))
    monkeypatch.setitem(sensibles.ETIQUETAS, "patente", "[PATENTE]")
    monkeypatch.setattr(sensibles, "REGLAS", [*sensibles.REGLAS, patente])
    assert sensibles.filtrar("Auto AB123CD en el taller") == ("Auto [PATENTE] en el taller", {"patente": 1})
