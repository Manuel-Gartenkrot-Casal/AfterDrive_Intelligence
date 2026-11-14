# Bitácora de QA como cliente

Una entrada por corrida, la más nueva arriba (como máximo las últimas 60). Cada una dice hasta qué
commit se revisó, qué se probó usando la app (no solo los tests), qué se encontró y qué quedó pendiente.

## 2026-11-14 · integración

- **Revisado hasta:** Render_Testing `18af701` · Render_Testing_2 `9f7f1db`. Sin cambios nuevos: tercera pasada, con lo que
  quedó pendiente el 13/11.
- **Probado como cliente:** Más opciones de Crear nota (regiones, clientes para mencionar y "No nombrar nunca", nombre
  vacío, repetido, recargar); vista previa de Instagram y LinkedIn de una nota con carrusel (escritorio y celular);
  terminal y cola de Desarrollador con una búsqueda de noticias (registro en vivo, maximizar, plegar, cerrar, recargar,
  Actividad). Todo sin errores de JavaScript ni scroll horizontal en celular.
- **Encontrado y arreglado:** "Agregar" un cliente con el nombre vacío no hacía nada y quedaba a la vista el mensaje
  "guardado" de la vez anterior. Ahora avisa "Escribí el nombre de la empresa." y pone el foco en el campo. Reproducir
  antes: Crear nota → Más opciones → agregar un cliente → borrar el nombre → Agregar. Test e2e
  `test_agregar_un_cliente_sin_nombre_avisa`.
- **Pregunta para el equipo:** volver a agregar un cliente que ya existe (aunque cambie la mayúscula) lo reemplaza sin
  avisar: el nombre queda como se escribió la última vez y la descripción se borra si no se completa. ¿Se quiere que
  avise que ya existía, o que conserve la descripción?
- **Preguntas abiertas:** las de corridas anteriores.

## 2026-11-13 · integración

- **Revisado hasta:** Render_Testing `18af701` · Render_Testing_2 `38f063d`. Sin cambios nuevos: segunda pasada de integración,
  en las zonas que ayer quedaron sin ver.
- **Probado como cliente:** vista Desarrollador (tablero de métricas, proveedor de IA con la API paga, en escritorio y
  celular, es/pt/en); imagen destacada (elegir la foto de una noticia desde Vista previa, guardar, recargar y quitarla).
  La API paga pide confirmación con el gasto y el tope, queda elegida al recargar y volver a NVIDIA no pide confirmar.
- **Encontrado y arreglado:**
  1. La primera tarjeta de Métricas decía "Fuentes registradas: 1" arriba de "2 registradas" (el 1 son las activas).
     Ahora dice "Fuentes activas". Reproducir antes: entrar en Desarrollador con una fuente pausada.
  2. El diálogo para elegir la API paga quedaba en español en pt/en (solo el título y los botones se traducían) y
     mostraba "USD 0.00 de un tope de USD 40". Ahora se traduce completo y los montos usan el formato del idioma.
     Reproducir antes: Desarrollador → interfaz en EN → tocar "API paga".
  3. Una nota sin imagen decía "Ninguna noticia de la nota tenía foto" aunque sus noticias tuvieran fotos (notas
     viejas, o después de quitar la imagen a mano). Ahora, si hay fotos, invita a elegir una. Reproducir antes:
     Vista previa → elegir la foto de una noticia → Quitar imagen → el aviso decía que ninguna tenía foto.
  Tests e2e: `test_la_tarjeta_de_fuentes_cuenta_las_activas`, `test_confirmar_la_api_paga_se_traduce_y_usa_el_formato_del_idioma`,
  `test_el_aviso_sin_imagen_dice_si_sus_noticias_tienen_fotos`.
- **Pendiente para otra corrida (tope de 3 arreglos):** Más opciones de Crear nota (regiones, clientes, empresas que no se
  nombran), vista previa de Instagram/LinkedIn, terminal y cola de Desarrollador.
- **Preguntas abiertas:** las de las corridas anteriores (aviso de cambios sin guardar después de generar, fuente
  repetida, evaluación con IA al abrir notas viejas).

## 2026-11-12 · integración

- **Revisado hasta:** Render_Testing `18af701` · Render_Testing_2 `c135ba4`. Sin cambios nuevos desde ayer: recorrido de punta a punta.
- **Probado como cliente** (vista Cliente; escritorio 1366x900 y celular 390x844; Prompts en es/pt/en):
  - Inicio: contadores (notas para revisar, noticias, fuentes activas, próxima nota) coinciden con Historial, Fuentes
    y Programación, y se actualizan al aprobar, pausar o reprogramar.
  - Revisar una nota: calificar (estrellas, etiqueta, comentario), editar el texto y aprobar y subir a HubSpot. Todo
    sobrevive a recargar y se ve igual en la lista, el Inicio, el contador de la barra lateral y los filtros por estado.
    Sin IA, la calificación de la IA avisa claro y la humana sigue andando.
  - Fuentes: agregar, repetir, pausar y reactivar; Programación: cambiar la hora, sumar una hora extra (presupuesto
    recalculado), guardar y recargar.
  - Crear nota: sin categorías avisa; con categoría encola la generación. Prompts: pestañas y editor.
  - Sin scroll horizontal en celular en ninguna sección y sin errores de JavaScript.
- **Encontrado y arreglado:** en Prompts, la cabecera "Prompt completo" decía "64 líneas · 115 caracteres": las líneas
  eran de todo el prompt y los caracteres solo de la pieza elegida, y parecía que el prompt entero tenía 115 caracteres.
  Ahora dice "64 líneas · Identidad: 115 caracteres" (también al entrar, no solo al cambiar de pieza). Para reproducirlo
  antes: entrar a Prompts y mirar la cabecera del prompt completo. Test e2e
  `test_prompts_los_caracteres_son_de_la_pieza_elegida`.
- **Preguntas para el equipo:**
  - Después de tocar "Generar nota", salir de Crear nota avisa "Tenés cambios sin guardar… se pierden los cambios" (son
    las categorías elegidas, que no se guardaron para la nota automática). Recién generada la nota, el aviso confunde:
    ¿debería decir que lo que no se guarda es la configuración de la nota automática?
  - Volver a agregar una fuente que ya estaba muestra "URL guardada como activa", igual que una nueva. ¿Avisar que ya
    estaba?
  - Sigue la de ayer: abrir una nota vieja sin `evaluacion` llama a la IA cada vez.
- **Observaciones menores:** la misma nota muestra en el Inicio la fecha de generación en "Última nota" y la del
  documento en "Para revisar" (en producción casi coinciden).
- **No se pudo probar acá:** la generación de punta a punta desde la interfaz (corre en un subproceso que no ve la base
  en memoria de la app de prueba); está cubierta por los tests unitarios.

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
