# Guía de uso

AfterDrive Intelligence busca noticias del sector autopartes en los sitios que elegís, las filtra con inteligencia artificial y escribe con ellas notas B2B para el blog de AfterDrive by Alephee. Vos revisás cada nota, la corregís si hace falta y la publicás en HubSpot.

Esta guía explica cada parte de la aplicación. Para un recorrido rápido en pantalla: **Ayuda → Repetir el tutorial**, al pie de la barra lateral.

## Cómo funciona, en tres pasos

1. **Juntar noticias.** Todos los días, a la hora que programes, el sistema revisa tus fuentes, guarda las noticias nuevas que son del rubro y descarta las que no (por ejemplo, venta de autos 0 km o seguros). De cada noticia guarda una ficha con sus datos principales.
2. **Escribir la nota.** Con las noticias más útiles y recientes, el sistema arma un plan, escribe la nota, verifica que cada cifra y cada empresa salgan de las noticias, revisa estilo y SEO y, si encuentra un problema, lo corrige. También genera una imagen destacada.
3. **Revisar y publicar.** La nota queda en **Historial** como "Para revisar". La leés, la calificás, la editás si querés, la aprobás y la publicás en el blog.

## Inicio

Es tu mesa editorial:

- **Notas para revisar**, noticias listas para usar, fuentes activas y cuándo sale la próxima nota automática. Tocá cualquiera para ir directo.
- **Última nota** generada, con un botón para leerla.
- **Para revisar**: las notas que esperan tu lectura.
- **Actividad del sistema**: lo que está haciendo ahora.

## Crear nota

Para escribir una nota cuando quieras, sin esperar a la automática.

| Opción | Para qué sirve |
|---|---|
| **Categorías** | El tema de la nota. Elegí una o más |
| **Tono** | Comercial, analítico-técnico, periodístico, divulgativo o ejecutivo |
| **Largo aproximado** | Corto (500 a 700 palabras), medio (700 a 1000) o largo (1000 a 1400) |
| **Tema específico** | Opcional, para acotar ("dropshipping en Argentina") |
| **Puntapié** | Un link al que la nota tiene que llevar al lector |
| **Regiones** (en "Más opciones") | El mercado y el idioma. Con Brasil la nota se escribe en portugués; sin región, en español rioplatense |
| **Clientes** (en "Más opciones") | Empresas que la nota puede mencionar como casos reales |

- **Generar nota** la escribe con lo que está en pantalla. Tarda unos minutos; podés seguir usando la aplicación mientras tanto.
- **Guardar cambios** deja esta configuración para la **nota automática** de cada día.

Toda nota termina con una sección **"Qué significa para tu negocio"** (acciones concretas para un distribuidor o un repuestero), **preguntas frecuentes** y la lista de **fuentes**.

## Historial

Cuatro listas, con buscador:

- **Notas**: las generadas, filtrables por estado (para revisar, aprobadas, publicadas, rechazadas).
- **Notas descartadas**: las que el sistema escribió pero no pasaron sus controles, con el motivo.
- **Artículos guardados** y **artículos descartados**: las noticias que se scrapearon, con el motivo del descarte.

### Revisar una nota

Al abrir una nota ves el texto y, al costado, lo que el sistema revisó:

- **Datos contra las noticias**: cuántos datos están respaldados y cuáles no. Los que dicen "sin respaldo" revisalos antes de publicar.
- **Estilo y SEO**: frases de relleno, anglicismos, largo del título y de la meta description, palabra clave, preguntas frecuentes.
- **Costo de esta nota**, si se usó la API paga.
- **Imagen destacada** y **el plan** que siguió la nota.

Acciones:

| Botón | Qué hace |
|---|---|
| **Aprobar** / **Rechazar** | Rechazar pide un motivo, que las próximas notas tienen en cuenta |
| **Editar** | Cambia el texto. La primera edición guarda la versión original, y las próximas notas aprenden de tus cambios |
| **Vista previa** | Cómo va a salir en el blog: título, meta description, etiquetas, imagen y cuerpo. Desde ahí también se cambia la imagen |
| **Borrador en HubSpot** / **Publicar en HubSpot** | Solo con la nota aprobada |

### Calificar notas

En la nota abierta: de 1 a 5 estrellas, etiquetas ("Suena a IA", "Muy larga", "Buen ángulo"…) y un comentario opcional. Es la forma más directa de mejorar las notas:

- Una etiqueta negativa que se repite agrega una regla a las próximas notas.
- Los comentarios de notas mal calificadas se usan como correcciones; los de las bien calificadas, como ejemplos de lo que funciona.
- Las notas con 4 o 5 estrellas pasan a ser referencias de estilo.
- Con 8 notas calificadas, la revisión automática se ajusta a tu criterio.

En **Historial → Cómo aprende la generación** ves todo lo que el sistema aprendió.

### Imagen destacada

Cada nota nueva sale con una imagen generada con IA (NVIDIA, sin costo). En **Vista previa** podés generar otra, describir lo que querés que muestre (mejor en inglés), pegar la URL de una imagen propia o quitarla. Al publicar, la imagen se sube a HubSpot.

## Programación

A qué hora y cada cuántos días se **buscan noticias** y se **escribe la nota automática**, y cuántos artículos se leen por fuente. Los cambios se aplican al tocar **Guardar cambios**. Las horas son de Argentina.

## Fuentes

Los sitios que se revisan para buscar noticias.

- **Agregar** suma la fuente directo.
- **Probar y agregar** la revisa primero y solo la suma si encuentra artículos del sector.
- **Pausar** deja de revisarla sin borrarla.
- **Buscar recomendaciones** sugiere sitios nuevos del sector.

## Corridas

Lo que el sistema está ejecutando (buscar noticias, generar una nota) y lo que espera su turno, con el registro de cada paso. Corre una cosa a la vez: lo que pidas mientras tanto queda en cola. Una corrida pendiente se puede cancelar.

## API paga

El interruptor **API paga** de la barra lateral pone todo el sistema en el proveedor pago durante **24 horas como máximo**: notas de más calidad, pero cada paso cuesta dinero. Pide confirmación, muestra cuánto se gastó en el mes y se apaga solo. Hay un tope de gasto mensual: si se alcanza, el sistema vuelve al proveedor gratuito.

## Vista Cliente y Desarrollador

- **Cliente** muestra lo esencial.
- **Desarrollador** suma la consola de procesos, las estadísticas técnicas y la elección del proveedor de IA.

## Preguntas frecuentes

**¿Por qué una nota salió en portugués?**
Porque entre las regiones estaba Brasil. Destildala en Crear nota → Más opciones.

**¿Qué hago con un dato "sin respaldo"?**
Buscalo en las noticias de la nota (están al costado). Si no está, editá la nota y sacalo o cambialo.

**La nota no tiene imagen.**
Al abrirla, el bloque "Imagen destacada" dice por qué. Generala desde Vista previa.

**¿Cómo hago para que las notas mejoren?**
Calificalas, contá en el comentario qué cambiarías y, cuando rechaces una, escribí el motivo. El sistema lo usa en las siguientes.

**¿Dónde veo cuánto costó una nota?**
Al abrirla, en "Costo de esta nota" (solo si se usó la API paga).
