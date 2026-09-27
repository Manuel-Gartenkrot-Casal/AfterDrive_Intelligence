# Rediseño del espacio editorial

Base revisada: `Render_Testing`, commit `c12618d` (27 de septiembre de 2026).

## Diagnóstico y alcance

La interfaz existente permite recopilar noticias, administrar fuentes, configurar
ejecuciones, generar artículos y notas, consultar el último resultado y evaluarlo.
Los usuarios inferidos del código son operadores de contenidos y redactores del
sector automotriz/postventa. La frecuencia de sus tareas todavía requiere validación
con usuarios reales.

La edición persistente, aprobación editorial y publicación en HubSpot aparecen en
la documentación como planes; no se encontraron recorridos completos para esas
capacidades en Flask. Por eso no se agregaron botones que las prometan.

Problemas observados:

- Funciones agrupadas por fases de implementación, con controles centrales ocultos.
  Se reemplazan por Redacción, Fuentes, Automatización y Actividad.
- La administración de fuentes precedía a la redacción dentro del mismo bloque.
  Cada tarea ahora tiene su espacio y se conservan sus controles originales.
- Tarjetas, campos y botones dependían de sombras similares para distinguirse.
  Se incorporan superficies, bordes, jerarquía y estados explícitos.
- Filtros construidos con divs sin interacción de teclado; modal sin contención ni
  restauración de foco. Se agregan semántica, teclado, Escape y retorno de foco.
- El refresco periódico sobrescribía campos de programación. La carga inicial ya
  no pisa ediciones; los interruptores se aplican mediante Guardar programación.
- Los guardados anunciaban éxito sin comprobar la respuesta HTTP. Ahora se
  comprueban y se muestran fallos; las escrituras de filtros se serializan.
- El resultado de artículo apuntaba a `/api/ultimo-articulo`, inexistente en Flask.
  Se corrige a `/ultimo-articulo` y se prueba el recorrido.

Decisión estética: azul tinta y petróleo, superficies planas, IBM Plex Sans para
lectura y controles, Barlow Condensed para títulos y cifras, monoespaciada limitada
a datos auxiliares. Es una interpretación editorial/técnica del rubro, no una
conclusión empírica sobre preferencias de los usuarios. La utilidad de iniciar en
Redacción en lugar de Fuentes debe contrastarse con el uso cotidiano.

Se preserva el HUD de Manu durante las corridas. La consola queda accesible desde
Actividad y desde el HUD. Las menciones de clientes son opcionales y desplegables.

## Implementación

- `express/src/public/index.html`: estructura y controladores existentes.
- `express/src/public/workspace.css`: sistema visual responsive, claro/oscuro.
- `express/src/public/workspace.js`: navegación, accesibilidad y foco.
- No hay framework nuevo ni dependencia de producción adicional.
- El build existente copia toda la carpeta public. En local hay que copiar los
  tres archivos a `static/`; esa carpeta continúa sin versionarse.

## Verificación reproducible

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe scripts/verify_dashboard.py --output "$env:TEMP/afterdrive-design"
```

La prueba de navegador usa Chromium de Playwright y respuestas API simuladas.
Intercepta todas las escrituras; no necesita Flask, Mongo ni proveedores de IA.
Solo permite salir a las dependencias CDN ya utilizadas por el frontend.

Comprueba navegación, teclado, filtros y payloads, generación de artículo y nota,
consulta del resultado, modal, preservación de ediciones, fallos HTTP y reintento,
fuentes vacías, streaming, errores de carga, 32 combinaciones de sección/tema/ancho
(1440, 768, 390, 320 px) y contraste de los pares principales de texto.

Resultados al implementar: 43 tests de Python aprobados; prueba de navegador
aprobada sin errores JS. Contraste mínimo entre pares comprobados: 5,46:1 claro y
5,98:1 oscuro. El script nuevo pasa Ruff. `ruff check .` reporta 76 incidencias en
archivos previos sin modificar; no se hizo una limpieza ajena a este alcance.

Se inspeccionó el render claro/oscuro y móvil. No se ejecutaron generaciones,
scraping ni escrituras contra Atlas/IA reales. Tampoco se certificó WCAG completo
ni se probó con lector de pantalla. Edición, aprobación y publicación necesitan
una definición de producto posterior.

## Revisión pendiente con Claude Code

Se intentó una consulta de solo lectura con Claude Code 2.1.283. El proceso
respondió `Credit balance is too low`; no participó en el diseño ni validó cambios.

Cuando tenga acceso, pedirle revisar el diff de estos archivos contra `c12618d`,
sin editar ni hacer commit/push y sin leer `.env`. Priorizar pérdida de controles,
contratos Flask, semántica de guardado, filtros tras reintentos, accesibilidad del
modal y tamaños móviles. Ejecutar la prueba aislada anterior antes de proponer
cambios. No ejecutar corridas ni escribir en servicios reales.

Los cambios quedan sin commit/push, pendientes de revisión visual del usuario.
