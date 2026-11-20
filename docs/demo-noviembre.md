# Demo de noviembre: guion

De punta a punta: **noticia → nota → revisión → HubSpot de pruebas**, con una nota enfocada en Alephee. Dura unos 15 minutos. La nota en vivo tarda de 3 a 6 minutos con la API paga: mientras se escribe se muestran Fuentes y Prompts.

Nada llega al blog real: la demo sube un **borrador** al blog de pruebas y solo si está cargado y prendido.

## El día antes

1. En el servidor (Render, *Environment*), revisá que estén cargadas:
   - `HUBSPOT_TOKEN` y `HUBSPOT_BLOG_PRUEBAS`, con el id del blog de pruebas;
   - `PAGA_API_KEY`, `PAGA_BASE_URL` y `PAGA_MODEL`, para la API paga.
2. Corré la preparación con las mismas variables:

   ```
   python -m scripts.demo_mode --solo-preparar
   ```

   - Prende el blog de pruebas y la API paga, que queda prendida un día.
   - Suma las fuentes recomendadas para Alephee a **Fuentes > Fuentes recomendadas**.
   - Lista lo que falte con `[FALTA]` y termina con error si falta algo.
3. Revisá el **enfoque Alephee** en **Prompts**: *Qué resuelve*, *Productos* y *Casos*.
   - Es lo único que la nota puede afirmar de Alephee.
   - Si hay un caso de cliente aprobado para mostrar, cargalo; si no, dejá la línea "Todavía no hay casos cargados".
   - Si en producción ya había una versión editada y activa del enfoque, sigue esa y no la nueva por defecto: sumale las tres secciones a mano.
4. En **Fuentes > Fuentes recomendadas**, agregá las que sirvan con **Probar y agregar**.
   - Las direcciones no se pudieron verificar al escribirlas.
   - Las que anuncian un RSS o son un sitemap se leen desde ahí.
5. Corré la demo completa una vez, para tener una nota de respaldo:

   ```
   python -m scripts.demo_mode --hubspot
   ```

   Si falla algo, queda escrito en la salida.

## En vivo

| # | Pantalla | Qué mostrar | Qué decir |
|---|---|---|---|
| 1 | **Inicio** | Notas para revisar, noticias listas, fuentes activas y próxima nota automática | El sistema trabaja solo todos los días: busca noticias, escribe y deja las notas para revisar |
| 2 | **Fuentes** | Una fuente activa y **Fuentes recomendadas** (marketplaces, e-commerce automotor, Alephee) | Las fuentes con RSS o sitemap se leen directo de ahí: más rápido y con la fecha de cada nota |
| 3 | **Crear nota** | Categorías *marketplaces*, *catalogacion* y *autopartes*; tema "vender autopartes en marketplaces con el catálogo al día"; región Argentina; largo corto. **Generar nota** | Elegimos de qué escribir; la IA elige las noticias y arma el plan sin repetir los ángulos ni las palabras clave de las últimas ~50 notas |
| 4 | **Prompts** (mientras se escribe) | El enfoque Alephee: *Qué resuelve*, *Productos* y *Casos*; el botón **Editar** | El equipo de contenido decide qué puede decir la nota de Alephee, sin tocar código; cada cambio se aprueba |
| 5 | **Historial > Revisar** | Datos contra las noticias, Estilo y SEO, imagen destacada y el plan | Cada cifra se busca en las noticias: lo que no aparece queda marcado "sin respaldo" |
| 6 | **Historial > Calificar** | **Checklist de Alephee** y la calificación sugerida por la IA | Un juez revisa que Alephee aparezca con motivo, sin inventar nada y con una sola llamada a la acción |
| 7 | **Aprobar y subir a HubSpot** | El botón sube la nota como borrador al blog de pruebas; abrir el link del borrador | Nada llega al blog sin que una persona lo apruebe. Hoy va al blog de pruebas |
| 8 | **Corridas** (vista Desarrollador) | La corrida de la nota y su costo | Cuánto costó esta nota con la API paga |

Desde la terminal, los pasos 3 a 7 son:

```
python -m scripts.demo_mode --sin-scraping --hubspot
```

Imprime la nota, los datos verificados, la calificación del juez y la checklist de Alephee. Después sube la nota.

## Plan B

| Si… | Hacé |
|---|---|
| No hay internet o las fuentes no responden | `python -m scripts.demo_mode --datos-ejemplo`: carga 4 noticias de ejemplo de `scripts/demo_datos.json` y escribe la nota con ellas. Cada una dice "Ejemplo para la demo" y su link termina en `.invalid` |
| La nota en vivo tarda o falla | Abrí la nota de respaldo del día antes en **Historial** |
| La API paga no prende (tope de gasto o sin claves) | La nota se escribe con el proveedor gratuito: tarda más y sale algo más floja. Mostrá la de respaldo |
| No hay blog de pruebas | No apruebes ni subas: mostrá la nota con **Vista previa**, al pie de la nota |

Después de la demo, borrá las noticias de ejemplo con `python -m scripts.demo_mode --limpiar`. Las notas que se escribieron con ellas quedan en el Historial: rechazalas con el motivo "demo".
