"""Usuario y clave del servidor e2e.

Aparte de servidor.py a propósito: importar servidor.py ejecuta su
os.environ.update y el parche de Mongo, y conftest lo cargaría dentro del
proceso de pytest, contaminando el entorno de los tests unitarios.
"""

USUARIO, CLAVE = "admin", "e2e-clave-123"
