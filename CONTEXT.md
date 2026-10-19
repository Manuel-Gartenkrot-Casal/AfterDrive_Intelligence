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

**Modo degradado**:
Estado en que el clasificador no está disponible y los artículos se aprueban sin juicio, para no perderlos por una caída ajena a su contenido.

### Notas

**Nota**:
Texto original de blog B2B generado por el pipeline a partir de Artículos o de ejemplos reales, listo para publicar.
_Avoid_: artículo generado, post, vlog

**Nota Fase 1**:
Nota escrita a partir de un tópico de Artículos elegido por similitud. El generador se borró; quedan las notas viejas.

**Nota Fase 2**:
Nota escrita imitando notas reales publicadas de AfterDrive (Ejemplos), según Categorías, Regiones y Clientes elegidos.

**Estado de una Nota**:
Dónde está en la revisión: borrador (recién generada), aprobada, rechazada (con un motivo, que pasa a ser una Corrección) o publicado (en el blog de HubSpot).

**Corrección**:
Motivo de rechazo reciente que se le pasa al modelo al escribir notas nuevas, como error a no repetir.
_Avoid_: status

**Nota descartada**:
Respuesta del modelo que el Saneo rechazó; se guarda con el motivo, nunca se publica.

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
Lista de Corridas esperando su turno; la que llega mientras otra corre espera en vez de rechazarse. Puede estar pendiente, en curso, ok, error, cancelada o interrumpida (el servidor se reinició mientras corría).
_Avoid_: queue, fila

**Proveedor**:
Servicio de IA que responde las llamadas del pipeline: LM Studio local, NVIDIA, OpenRouter o la API paga.
_Avoid_: provider, backend, modelo

**Ficha**:
Resumen estructurado de un Artículo (resumen, hechos, cifras, empresas, fecha) que la generación usa en lugar del cuerpo crudo.

**Plan**:
Ángulo, título, palabra clave y secciones de una Nota, decididos antes de redactarla.

**Calificación**:
Puntaje de 1 a 5 estrellas, con etiquetas y comentario, que una persona le pone a una Nota.
_Avoid_: rating, voto

**Calibración**:
Lo que la generación aprende de calificaciones, rechazos y ediciones: correcciones, referencias propias y el umbral del evaluador.

**Modo pago**:
Estado en que todo el pipeline usa la API paga por 24 horas como máximo; se prende desde la vista Cliente y se apaga solo.
_Avoid_: modo premium, API paga activada
