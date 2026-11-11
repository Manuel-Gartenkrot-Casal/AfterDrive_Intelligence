# Bitácora de QA como cliente

Una entrada por corrida, la más nueva arriba (como máximo las últimas 60). Cada una dice hasta qué
commit se revisó, qué se probó usando la app (no solo los tests), qué se encontró y qué quedó pendiente.

## 2026-11-11 · diario

- **Revisado hasta:** Render_Testing `18af701` · Render_Testing_2 `930719c` (primera corrida: cambios de los últimos días).
- **Cambios revisados:** `18af701` (la barra de la nota abierta mide lo mismo que el encabezado) y, por compartir
  pantalla, `1a0fb0e` del PR #24 (vista Cliente por defecto, "Métricas" en Desarrollador, panel "Tu nota" sin hueco).
- **Probado como cliente** (app de prueba con `tests.e2e.servidor` y Playwright):
  - Abrir una nota desde Notas en la vista Cliente, escritorio 1366x900: la barra mide 68px como el encabezado y su
    línea sigue a la del logo. En celular 390x844 la barra es de dos renglones y tapa la pantalla (diseño distinto, bien).
  - Entrar con un `ad-modo=dev` viejo en localStorage: arranca en Cliente. Pasar a Desarrollador y recargar: sigue en
    Desarrollador. Ayuda → "Pasar a la vista Cliente": confirma y cambia. Cerrar sesión y volver a entrar: Cliente.
  - "Inicio"/"Métricas" según la vista en es, pt (Início/Métricas) y en (Home/Metrics).
  - Crear nota en 1366x900, 1366x700, 1920x1080 y 390x844: el panel "Tu nota" es sticky y al hacer scroll entra justo
    en la ventana, sin cortar contenido; "Cómo se arma tu nota" como línea de tiempo.
  - Sin errores de JavaScript ni scroll horizontal en celular.
- **Encontrado:** nada roto en lo revisado.
- **Agregado:** e2e `test_al_volver_a_entrar_arranca_en_cliente` (no estaba cubierto que cerrar sesión o un "dev" viejo
  no dejen la app en Desarrollador; se comprobó que falla si `salir()` no borra la vista).
- **Pregunta para el equipo:** al abrir una nota que no tiene `evaluacion` guardada (notas viejas), el dashboard llama
  a `/api/evaluate-article` cada vez que se abre: es una llamada a la IA (con costo si va a la API paga) cuyo resultado
  no se guarda, y sin IA disponible responde 500. ¿Conviene guardar esa evaluación la primera vez, o no evaluar al abrir?
- **Pendiente:** ninguno.
