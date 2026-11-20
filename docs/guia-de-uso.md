# Guía de uso

AfterDrive Intelligence busca noticias del sector autopartes en los sitios que elegís, las filtra con inteligencia artificial y escribe con ellas notas B2B para el blog de AfterDrive by Alephee. Vos revisás cada nota, la corregís si hace falta y la subís a HubSpot como borrador; la publicación final se hace en HubSpot.

Esta guía explica cada parte de la aplicación. Para un recorrido en pantalla: **Ayuda**, al pie de la barra lateral. Ahí está el tutorial completo y tres cortos: **Crear mi primera nota**, **Revisar y publicar** y **Programar tareas**.

> El idioma de la interfaz (Español, Português, English) se cambia con los botones **ES / PT / EN** arriba a la derecha o en el primer paso del tutorial. Cambia solo la interfaz, no las notas: todas se escriben en portugués y se traducen al español y al inglés (ver **Crear nota**).

## Cómo funciona, en tres pasos

1. **Juntar noticias.** Todos los días, a la hora que programes, el sistema revisa tus fuentes, guarda las noticias nuevas que son del rubro y descarta las que no (por ejemplo, venta de autos 0 km o seguros). De cada noticia guarda una ficha con sus datos principales.
2. **Escribir la nota.** Con las noticias más útiles y recientes, el sistema arma un plan, escribe la nota, verifica que cada cifra y cada empresa salgan de las noticias, revisa estilo y SEO y, si encuentra un problema, lo corrige. Le elige 3 fotos de esas noticias, la traduce a los otros dos idiomas y una IA la califica.
3. **Revisar y subir.** La nota queda en **Historial** como "Para revisar". La revisás, la calificás, la editás si querés y la aprobás: se sube a HubSpot como borrador, en portugués, español e inglés.

La pantalla se actualiza sola cada pocos segundos: lo que cambia otra persona o una tarea del sistema aparece sin recargar. Si otro cambió la nota que tenés abierta, aparece un aviso con **Actualizar**.

## Inicio

Es tu contenido de hoy:

- **Notas para revisar**, noticias listas para usar, fuentes activas y cuándo sale la próxima nota automática. Tocá cualquiera para ir directo.
- **Última nota** generada, con un botón para leerla.
- **Para revisar**: las notas que esperan tu lectura.
- **Actividad del sistema**: lo que está haciendo ahora.

En la vista Desarrollador, Inicio muestra en cambio un tablero con lo que trajo el scraping, las notas escritas, las corridas y el consumo de la IA.

## Crear nota

Para escribir una nota cuando quieras, sin esperar a la automática.

| Opción | Para qué sirve |
|---|---|
| **Categorías** | El tema de la nota. Elegí una o más |
| **Tono** | Comercial, analítico-técnico, periodístico, divulgativo o ejecutivo |
| **Largo aproximado** | Corto (500 a 700 palabras), medio (700 a 1000) o largo (1000 a 1400) |
| **Tema específico** | Opcional, para acotar ("dropshipping en Argentina") |
| **Puntapié** | Un link al que la nota tiene que llevar al lector |
| **Regiones** (en "Más opciones") | El mercado del que habla la nota. **No cambian el idioma** |
| **Clientes** (en "Más opciones") | Empresas que la nota puede mencionar como casos reales |

**Idioma de la nota** muestra en qué idioma se escribe: portugués. Apenas se crea, se traduce al español y al inglés; las tres versiones se ven y se editan en el Historial.

- **Generar nota** la escribe con lo que está en pantalla. Tarda unos minutos; podés seguir usando la aplicación mientras tanto. Mientras se escribe, ves en qué paso va y la podés cancelar (no se guarda nada).
- **Guardar cambios** deja esta configuración para la **nota automática** de cada día.

Toda nota termina con una sección **"Qué significa para tu negocio"** (acciones concretas para un distribuidor o un repuestero), **preguntas frecuentes** y la lista de **fuentes**.

## Historial

Cuatro listas, con buscador:

- **Notas**: las generadas, filtrables por estado (para revisar, aprobadas, publicadas, rechazadas). Cada una muestra sus estrellas: las tuyas y, con la marca **IA**, las de la calificación de la IA.
- **Notas descartadas**: las que el sistema escribió pero no pasaron sus controles, con el motivo.
- **Artículos guardados** y **artículos descartados**: las noticias que se scrapearon, con el motivo del descarte.

### Revisar una nota

Al abrir una nota ves el texto y, al costado, la revisión en tres pasos. Abre en el primer paso que tiene algo pendiente. En el celular elegís si ver la nota o la revisión.

**1. Revisar**: lo que el sistema chequeó al escribirla. Arriba lo que necesita atención y después lo que está bien; cada fila tiene un titular, **Ver detalle** y, si corresponde, su acción.

- **Datos contra las noticias**: cuántos datos están respaldados y cuáles no. Los que dicen "sin respaldo" revisalos antes de publicar.
- **Parecida a una nota reciente**: si se parece demasiado a otra reciente.
- **Estilo y SEO**: frases de relleno, anglicismos, largo del título y de la meta description, palabra clave, preguntas frecuentes.
- **Lineamientos**, **imagen** e **idiomas**.
- **Cómo se generó**: el plan, las categorías, las noticias, las citas a AfterDrive, lo que costó (si se usó la API paga) y los criterios automáticos.

**2. Calificar**: la calificación de la IA y la tuya (ver **Calificar notas**).

**3. Publicar**: la imagen destacada, a qué blog de HubSpot va, con qué etiqueta y qué autor (por defecto, Gastón Zelerteins), y una fila por idioma con **Ver traducción** y **Abrir en HubSpot**.

El botón principal, abajo a la derecha, cambia según el paso: **Siguiente: calificar →** y **Siguiente: publicar →** en los dos primeros y, en Publicar, la acción que toca:

| Botón | Qué hace |
|---|---|
| **Aprobar y subir a HubSpot** | Aprueba la nota y la sube como borrador al blog de su idioma, firmada por el autor elegido. Después se suben las traducciones |
| **Subir borrador a HubSpot** / **Actualizar borrador en HubSpot** | Con la nota aprobada: reintenta si la subida falló, o actualiza el mismo borrador con tus cambios |
| **Editar** | Cambia el texto. La primera edición guarda la versión original, y las próximas notas aprenden de tus cambios |
| **Vista previa** | Cómo va a salir en el blog: título, meta description, etiquetas, imagen y cuerpo. Desde ahí también se cambia la imagen |
| **Más ▾** | Copiar texto, Ver en HubSpot, Volver a revisar y **Rechazar**, que pide un motivo que las próximas notas tienen en cuenta |

> **Publicar desde la aplicación está desactivado por ahora.** Las notas solo se suben como borrador y se publican desde HubSpot.

### Calificar notas

El paso **Calificar** tiene dos partes:

- **Calificación de la IA**: un corrector de estilo con IA le pone a la redacción un puntaje de 1 a 10, con barras de gramática, redacción, tono y estructura, y marca los errores que cometió al escribir: el fragmento, qué está mal y cómo quedaría bien. Se hace sola al generar la nota (y otra vez si la editás). Es informativa: no cuenta para el aprendizaje. Se lee en el idioma de la interfaz; el fragmento y su corrección quedan en el idioma de la nota.
- **Calificar esta nota**: tu calificación, de 1 a 5 estrellas, con etiquetas ("Suena a IA", "Muy larga o repetitiva", "Buen ángulo"…) y un comentario opcional. Si todavía no la calificaste, aparece precargada la que sugiere el juez de IA; solo cuenta cuando la guardás.

Tu calificación es la forma más directa de mejorar las notas:

- Una etiqueta negativa que se repite agrega una regla a las próximas notas.
- Los comentarios de notas mal calificadas se usan como correcciones; los de las bien calificadas, como ejemplos de lo que funciona.
- Las notas con 4 o 5 estrellas pasan a ser referencias de estilo.
- Con 8 notas calificadas, la revisión automática se ajusta a tu criterio.

En **Historial → Cómo aprende la generación** ves todo lo que el sistema aprendió y cuántas veces el juez de IA acertó tu calificación.

### Imágenes

Cada nota sale con **3 fotos** de las noticias que usó: la destacada (portada) y 2 dentro del texto. La IA las elige según el tema de la nota (con la API paga, las mira) y descarta logos, banners, gráficos y fotos de otra cosa. Además:

- **La portada nunca lleva personas.** Una foto con personas puede ir dentro del texto, pero no de portada. Si todas las aptas tienen personas, la nota queda sin portada y la revisión lo explica.
- **No se repiten fotos**: una foto que ya está en otra nota de los últimos 30 días no se vuelve a usar.
- Si las noticias de la nota no alcanzan, se buscan fotos en otras noticias del mismo tema.

En **Vista previa** podés elegir la foto de otra de sus noticias (las que tienen personas aparecen marcadas), pegar la URL de una imagen, **arrastrar una imagen o elegirla desde tu computadora** (JPG, PNG, WebP o GIF, hasta 5 MB) o quitarla. Al subir la nota, las imágenes se copian a HubSpot. Ojo: son fotos de otros medios; revisá que se puedan usar antes de publicar.

### Otros idiomas y citas

Apenas se crea, la nota se traduce al español y al inglés. En la nota abierta, las pestañas **Português**, **Español** y **English** muestran cada versión, que se edita por separado. Si editás el texto principal, las traducciones quedan desactualizadas: **Volver a traducir** las rehace.

Al aprobar y subir la nota, cada versión se sube a HubSpot como borrador, vinculada a la original. Lo ves en **Actividad** y en el paso **Publicar**. Si una falla, **Volver a subir las traducciones** reintenta.

Cuando encaja con el tema, la nota cita notas anteriores de AfterDrive by Alephee y las enlaza. Las ves en **Cómo se generó**.

## Programación

A qué hora y cada cuántos días se **buscan noticias** y se **escribe la nota automática**, y cuántos artículos se leen por fuente. Los cambios se aplican al tocar **Guardar cambios**. Las horas son de Argentina.

## Fuentes

Los sitios que se revisan para buscar noticias.

- **Agregar** suma la fuente directo.
- **Probar y agregar** la revisa primero y solo la suma si encuentra artículos del sector. Si el sitio no responde, lo avisa.
- **Pausar** deja de revisarla sin borrarla.
- **Buscar recomendaciones** sugiere sitios nuevos del sector: los busca en Google Noticias y otros buscadores y también le pide ideas a la IA (cada sitio se verifica antes de sugerirlo).

## Prompts

Las instrucciones que recibe la IA al escribir cada nota, en piezas (identidad, audiencia, reglas de datos, enfoque Alephee, formato, SEO y una por persona). Cada cambio a mano pasa por borrador, revisión y aprobación.

Prompts tiene dos pestañas: **Prompts actuales** (los de arriba) y **Prompts de la IA**, que los mejora sin que los escribas vos. La IA lee cómo salen calificadas las notas (la crítica, el juez, tus calificaciones y la checklist de Alephee), encuentra qué se repite y en qué pieza tocar, y cambia una **copia** de los prompts. Los prompts actuales no cambian nunca desde acá.

- **Mejora automática**: prendida, la IA mejora la copia sola cada 5 notas nuevas.
- **Analizar y mejorar ahora** lo hace en el momento.
- La pestaña muestra el prompt completo de la IA con lo que cambió marcado en verde (lo que sacó, en rojo), el análisis de las notas, el historial y un lugar para pedirle un cambio a mano (por ejemplo, "que use voseo en toda la nota").
- Si un cambio no te gusta, **Deshacer el último**; **Volver al actual** borra los cambios de una pieza.
- **Usar estos prompts** hace que la redacción escriba con los de la IA; la pestaña que está en uso dice **En uso**.

## Actividad

Lo que el sistema está ejecutando (buscar noticias, generar una nota, subir traducciones) y lo que espera su turno, con el registro de cada paso. Corre una cosa a la vez: lo que pidas mientras tanto queda en cola. Cualquier tarea se puede cancelar, también la que está corriendo. Al terminar un scraping, el registro dice cuánto se gastó de la API paga.

Mientras algo corre, un panel flotante abajo a la derecha te lo muestra desde cualquier sección; lo podés plegar.

En la vista Desarrollador, mientras algo corre, abajo aparece la **terminal** con el registro en vivo y, en la pestaña **Cola**, lo que espera. Se agranda arrastrando su borde de arriba, se maximiza o se oculta con los botones de la derecha, y se cierra con la ×.

## API paga

La **API paga** se elige en la vista Desarrollador, en **Proveedor de IA**, y se distingue del resto por el ícono **$**. Da notas de más calidad, pero cada paso cuesta dinero: al elegirla pide confirmación y muestra cuánto se gastó en el mes. Queda así hasta que elijas otro proveedor. Hay un tope de gasto mensual: si se alcanza, el sistema pasa solo al proveedor gratuito.

## Vista Cliente y Desarrollador

- **Cliente** muestra lo esencial. Para pasar a Desarrollador o cerrar sesión, tocá tu usuario abajo de la barra lateral.
- **Desarrollador** suma la consola de procesos, el tablero de métricas, la elección del proveedor de IA y dos interruptores:
  - **Borradores en HubSpot → blog_test**: prendido, los borradores van al blog de pruebas de HubSpot en vez de a los blogs de cada idioma. Si el servidor no tiene un blog de pruebas configurado, aparece desactivado.
  - **Aprobación automática**: prendida, la nota de la generación programada que pasa los controles y el juez de IA (con buena confianza) se aprueba sola y sube a HubSpot como borrador. Si no pasa, queda para revisar con los motivos. Nunca publica. Las notas que generás a mano siempre esperan tu revisión.

## Preguntas frecuentes

**¿Por qué las notas salen en portugués?**
Porque es el idioma principal del blog. Cada nota se traduce al español y al inglés al crearla: cambiá de pestaña en la nota abierta.

**¿Qué hago con un dato "sin respaldo"?**
Buscalo en las noticias de la nota (están en **Cómo se generó**). Si no está, editá la nota y sacalo o cambialo.

**La nota no tiene imagen destacada.**
Ninguna foto de sus noticias era apta o todas mostraban personas; el motivo está en el paso Revisar. Elegí otra desde Vista previa, pegá una URL o subí una imagen desde tu computadora.

**¿Por qué no puedo publicar desde acá?**
Está desactivado por ahora: la nota se sube como borrador y se publica desde HubSpot.

**¿Cómo hago para que las notas mejoren?**
Calificalas, contá en el comentario qué cambiarías y, cuando rechaces una, escribí el motivo. El sistema lo usa en las siguientes.

**¿Dónde veo cuánto costó una nota?**
Al abrirla, en **Cómo se generó** (solo si se usó la API paga).
