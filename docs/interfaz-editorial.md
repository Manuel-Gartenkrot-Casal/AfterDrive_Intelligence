# Interfaz editorial

La identidad de AfterDrive conserva el rosa y la base violeta. El rosa marca
acciones principales y selección; las acciones secundarias usan superficies
neutras. El turquesa indica procesamiento, sin inventar porcentajes de avance.
IBM Plex Sans y radios de 5–6 px en controles y 10 px en contenedores reemplazan
el tratamiento redondeado anterior. Los estados conservan texto e iconos.

La sección visible **Actividad** mantiene el hash `#corridas` y las API
`/api/corridas` para conservar enlaces e integraciones existentes. La navegación
móvil se abre desde Menú. El dock de actividad flota abajo a la derecha, acompaña
las tareas entre secciones y respeta la decisión de plegarlo; no achica el
contenido ni la barra lateral (su lugar va al final del scroll). En escritorio el
header y la barra lateral quedan quietos y solo scrollea el contenido. El gráfico
de etapas del pipeline se quitó: queda la línea animada del header. Las
animaciones respetan `prefers-reduced-motion`.

En Crear nota se muestra el idioma en el que se escriben todas las notas
(portugués); las regiones eligen el mercado, no el idioma. La ayuda ofrece
recorridos cortos para crear, revisar y programar, además del recorrido completo.

La revisión de una nota es un recorrido de tres pasos (Revisar → Calificar →
Publicar) con una sola acción principal en el pie. El tono es sobrio: pestañas
de texto, chequeos en una lista con puntos de estado, títulos neutros y la
calificación de la IA tipográfica, sin semáforo, íconos en círculos ni etiquetas
de colores. Las etiquetas elegidas de la calificación humana se marcan con borde,
fondo y tilde del color de su sentido, sin cambiar de ancho.
