# AfterDrive Intelligence

Pipeline que junta noticias del sector autopartes/aftermarket y las convierte en notas de blog B2B para AfterDrive by Alephee.

## Language

### Fuentes y artículos

**Fuente confiable**:
Sitio de noticias del sector que el pipeline scrapea periódicamente; está activa o inactiva.
_Avoid_: trusted URL, fuente custom

**Artículo**:
Noticia scrapeada de una Fuente confiable que pasó la clasificación y quedó guardada como materia prima.
_Avoid_: item, nota cruda, doc

**Artículo descartado**:
Artículo que la clasificación rechazó; se recuerda solo para no volver a procesarlo.

**Ingesta**:
Paso de un lote de artículos scrapeados a Artículos guardados: clasificar, vectorizar y guardar.
_Avoid_: clasificar y guardar

**Pendiente**:
Artículo que no se pudo clasificar porque la IA no respondió. No se guarda ni se descarta: la próxima corrida lo vuelve a clasificar. Reemplaza al viejo "modo degradado", que lo aprobaba sin juicio.

### Notas

**Nota**:
Texto original de blog B2B generado por el pipeline a partir de Artículos o de ejemplos reales, listo para publicar.
_Avoid_: artículo generado, post, vlog

**Nota Fase 1**:
Nota escrita a partir de un tópico de Artículos elegido por similitud. El generador se borró; quedan las notas viejas.

**Nota Fase 2**:
Nota escrita imitando notas reales publicadas de AfterDrive (Ejemplos), según Categorías, Regiones y Clientes elegidos.

**Estado de una Nota**:
Dónde está en la revisión: borrador (recién generada), aprobada (por una persona o por la Aprobación automática; al aprobarla se sube a HubSpot como borrador), rechazada (con un motivo, que pasa a ser una Corrección) o publicado (en el blog de HubSpot). Hoy el dashboard no publica: el paso a publicado se hace en HubSpot.

**Imagen destacada**:
Foto de portada de una Nota, elegida entre las fotos de sus Artículos; nunca muestra personas. Cada Nota lleva además 2 fotos dentro del texto.
_Avoid_: portada IA, imagen generada

**Corrección**:
Motivo de rechazo reciente que se le pasa al modelo al escribir notas nuevas, como error a no repetir.
_Avoid_: status

**Nota descartada**:
Respuesta del modelo que el Saneo rechazó; se guarda con el motivo, nunca se publica.

**Traducción**:
Versión de una Nota en otro idioma del blog. Las Notas se escriben en portugués y se traducen al español y al inglés al crearse; cada versión se edita por separado y se sube a HubSpot como borrador vinculado al post original.
_Avoid_: variante, copia

**Ejemplo**:
Nota real publicada en el blog de AfterDrive, usada como referencia de tono y estructura.

**Persona**:
Estilo de redacción de una Nota: analítico, periodístico, comercial, divulgativo o ejecutivo.
_Avoid_: personalidad, tono

**Puntapié**:
Modalidad de Nota cuyo objetivo es llevar al lector a una URL puntual.

**Cliente**:
Empresa que una Nota puede mencionar como caso real del sector.

**Saneo**:
Paso que convierte la respuesta cruda del modelo en una Nota publicable, o la rechaza con un motivo.

### Operación

**Corrida**:
Ejecución puntual de una etapa del pipeline (scraping, generación u otro script); nunca corren dos a la vez.
_Avoid_: job, tarea, ejecución

**Cola**:
Lista de Corridas esperando su turno; la que llega mientras otra corre espera en vez de rechazarse. Puede estar pendiente, en curso, ok, error, cancelada o interrumpida (el servidor se reinició mientras corría). En el dashboard se ve en la sección **Actividad** (el código y la API siguen diciendo "corridas").
_Avoid_: queue, fila

**Proveedor**:
Servicio de IA que responde las llamadas del pipeline: LM Studio local, NVIDIA, OpenRouter o la API paga.
_Avoid_: provider, backend, modelo

**Ficha**:
Resumen estructurado de un Artículo (resumen, hechos, cifras, empresas, fecha) que la generación usa en lugar del cuerpo crudo.

**Plan**:
Ángulo, título, palabra clave y secciones de una Nota, decididos antes de redactarla.

**Calificación**:
Puntaje de 1 a 5 estrellas, con etiquetas y comentario, que una persona le pone a una Nota. Es la única que cuenta para la Calibración.
_Avoid_: rating, voto

**Juez**:
IA que actúa de editor exigente: al generar cada Nota dice si podría aprobarse sola, con qué confianza, y sugiere una Calificación. La sugerencia aparece precargada al revisar, pero no cuenta hasta que una persona la guarda.

**Aprobación automática**:
Interruptor de la vista Desarrollador: la Nota de la generación programada que pasa el filtro sin IA y el Juez (con confianza de 0,8 o más) se aprueba sola y sube a HubSpot como borrador. Nunca publica.

**Calificación de la IA**:
Crítica de la redacción de una Nota (gramática, ortografía, redacción, tono y estructura) con puntaje de 1 a 10 y cada error marcado. Es informativa: no toca la Calificación ni la Calibración.
_Avoid_: crítica (en la interfaz), corrección

**Calibración**:
Lo que la generación aprende de calificaciones, rechazos y ediciones: correcciones, referencias propias y el umbral del evaluador.

**Modo pago**:
Estado en que todo el pipeline usa la API paga por 24 horas como máximo y después se apaga solo. Hoy el dashboard no tiene el interruptor: se prende por la API (`POST /api/modo-pago`). Elegir "API paga" como proveedor, en cambio, no vence.
_Avoid_: modo premium, API paga activada
