/* Historial de Artículos y Notas guardados en la base.
 *
 * Cuatro secciones (generados/scrapeados x aprobados/descartados) con
 * búsqueda, paginación, motivo de descarte y estado editorial de las Notas.
 * Los datos vienen de /api/historial/*; ver historial.py para el contrato.
 *
 * Todo texto que llega de la base se inserta como texto, nunca como HTML:
 * incluye cuerpos scrapeados de sitios de terceros y salida cruda del modelo.
 * El único HTML que se genera a partir de contenido es el markdown de las
 * Notas, pasado por mdSeguro (sin HTML embebido y solo links http/https).
 */
(function () {
  'use strict';

  const SECCIONES = {
    generados_aprobados: {
      vacio: 'Todavía no hay notas generadas.',
    },
    generados_descartados: {
      vacio: 'No hay notas descartadas registradas. Se guardan desde esta versión: las anteriores solo quedaron en la consola.',
    },
    scrapeados_aprobados: {
      vacio: 'Todavía no hay artículos recopilados.',
    },
    scrapeados_descartados: {
      vacio: 'No hay artículos descartados.',
    },
  };
  const POR_PAGINA = 20;

  const estado = {
    seccion: 'generados_aprobados',
    pagina: 1,
    q: '',
    filtroEstado: 'todos',
    sinMotivo: 0,
    cargado: false,
    pedido: 0, // descarta respuestas viejas si el usuario cambia rápido de filtro
  };

  const $ = id => document.getElementById(id);

  // ── Render seguro ─────────────────────────────────────────────────────────
  function el(tag, attrs = {}, ...hijos) {
    const nodo = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') nodo.className = v;
      else if (k === 'text') nodo.textContent = v;
      else if (k.startsWith('on')) nodo.addEventListener(k.slice(2), v);
      else nodo.setAttribute(k, v === true ? '' : v);
    }
    nodo.append(...hijos.filter(h => h !== null && h !== undefined && h !== false));
    return nodo;
  }

  const esLinkSeguro = href => /^(https?:|mailto:)/i.test(String(href || '').trim());

  const mdSeguro = (() => {
    if (!window.marked || typeof window.marked.Marked !== 'function') return null;
    const md = new window.marked.Marked();
    md.use({
      renderer: {
        html() { return ''; },
        link(token) {
          const texto = this.parser.parseInline(token.tokens);
          if (!esLinkSeguro(token.href)) return texto;
          const a = el('a', {href: token.href, target: '_blank', rel: 'noopener noreferrer'});
          a.innerHTML = texto; // texto ya escapado por marked
          return a.outerHTML;
        },
        image(token) {
          return el('span', {text: token.text || ''}).outerHTML;
        },
      },
    });
    return md;
  })();

  function textoComoParrafos(texto) {
    const frag = document.createDocumentFragment();
    String(texto || '').split(/\n{2,}|\r\n\r\n/).map(p => p.trim()).filter(Boolean)
      .forEach(p => frag.append(el('p', {text: p})));
    return frag;
  }

  function renderContenido(destino, item) {
    destino.replaceChildren();
    const texto = item.contenido || '';
    if (!texto.trim()) {
      destino.append(el('p', {class: 'hist-muted', text: 'No hay contenido guardado para este elemento.'}));
      return;
    }
    // Las Notas son markdown; los artículos scrapeados, texto plano.
    if (item.seccion.startsWith('generados') && mdSeguro) {
      destino.innerHTML = mdSeguro.parse(texto);
    } else {
      destino.append(textoComoParrafos(texto));
    }
  }

  // ── Formato ───────────────────────────────────────────────────────────────
  const fmtFecha = iso => {
    if (!iso) return 'Fecha desconocida';
    const d = new Date(iso);
    return isNaN(d) ? 'Fecha desconocida' : d.toLocaleString('es-AR', {dateStyle: 'medium', timeStyle: 'short'});
  };
  const fmtNum = n => Number(n || 0).toLocaleString('es-AR');

  function badgeEstado(item) {
    const publicado = item.estado === 'publicado';
    return el('span', {
      class: 'hist-estado ' + (publicado ? 'is-publicado' : 'is-borrador'),
      text: publicado ? 'Publicado' : 'Borrador',
    });
  }

  function metaTexto(item) {
    const partes = [fmtFecha(item.fecha), item.origen];
    const m = item.meta || {};
    if (m.persona) partes.push('Voz ' + m.persona);
    if (m.tema && m.tema !== item.titulo) partes.push('Tema: ' + m.tema);
    if (Array.isArray(m.categorias) && m.categorias.length) partes.push(m.categorias.join(', '));
    if (m.fuente && m.fuente !== 'custom') partes.push(m.fuente);
    return partes.filter(Boolean).join(' · ');
  }

  // ── Resumen y pestañas ──────────────────────────────────────────────────
  async function cargarResumen() {
    try {
      const r = await fetch('/api/historial/resumen');
      const d = await r.json();
      if (!d.success) throw new Error(d.error);
      for (const seccion of Object.keys(SECCIONES)) {
        $('hist-count-' + seccion).textContent = fmtNum(d[seccion].total);
      }
      const g = d.generados_aprobados;
      $('hist-pub-total').textContent = fmtNum(g.total);
      $('hist-pub-publicados').textContent = fmtNum(g.publicados);
      $('hist-pub-borradores').textContent = fmtNum(g.borradores);
      const pct = g.total ? Math.round((g.publicados / g.total) * 100) : 0;
      $('hist-pub-barra').style.setProperty('--hist-pub', pct + '%');
      $('hist-pub-barra').setAttribute('aria-valuenow', String(pct));
      $('hist-pub-barra').setAttribute('aria-valuetext', `${pct}% publicadas`);
      const sinMotivo = d.scrapeados_descartados.sin_motivo;
      estado.sinMotivo = sinMotivo;
      actualizarAvisoSinMotivo();
      $('hist-sin-motivo').textContent = sinMotivo
        ? `${fmtNum(sinMotivo)} descartados antes de esta versión no tienen el motivo registrado.`
        : '';
    } catch (e) {
      Object.keys(SECCIONES).forEach(s => { $('hist-count-' + s).textContent = '—'; });
    }
  }

  // El aviso habla solo de los artículos scrapeados descartados.
  function actualizarAvisoSinMotivo() {
    $('hist-sin-motivo').hidden = !(estado.sinMotivo && estado.seccion === 'scrapeados_descartados');
  }

  function seleccionarSeccion(seccion, enfocar = false) {
    estado.seccion = seccion;
    estado.pagina = 1;
    document.querySelectorAll('#hist-tabs [role="tab"]').forEach(tab => {
      const activo = tab.dataset.seccion === seccion;
      tab.setAttribute('aria-selected', String(activo));
      tab.tabIndex = activo ? 0 : -1;
      if (activo && enfocar) tab.focus();
    });
    $('hist-panel').setAttribute('aria-labelledby', 'hist-tab-' + seccion);
    const conEstado = seccion === 'generados_aprobados';
    $('hist-filtro-estado').hidden = !conEstado;
    $('hist-pub-resumen').hidden = !conEstado;
    actualizarAvisoSinMotivo();
    cargarLista();
  }

  // ── Listado ───────────────────────────────────────────────────────────────
  function renderItem(item) {
    const esGenerado = item.seccion.startsWith('generados');
    const esDescartado = item.seccion.endsWith('descartados');

    const cabecera = el('div', {class: 'hist-item-head'},
      el('h3', {class: 'hist-item-title'},
        el('button', {class: 'hist-item-link', type: 'button', text: item.titulo,
          onclick: () => abrirDetalle(item)})),
      item.seccion === 'generados_aprobados' ? badgeEstado(item) : null);

    const motivo = esDescartado
      ? el('p', {class: 'hist-motivo' + (item.motivo ? '' : ' is-desconocido')},
          el('strong', {text: 'Motivo: '}),
          item.motivo || 'no registrado (descartado antes de que se guardara el motivo)')
      : null;

    const acciones = el('div', {class: 'hist-item-actions'},
      el('button', {class: 'btn btn-sm', type: 'button', text: 'Ver completo', onclick: () => abrirDetalle(item)}),
      item.seccion === 'generados_aprobados' ? botonEstado(item) : null,
      !esGenerado && esLinkSeguro(item.url)
        ? el('a', {class: 'btn btn-sm', href: item.url, target: '_blank', rel: 'noopener noreferrer', text: 'Abrir fuente ↗'})
        : null);

    return el('li', {class: 'hist-item' + (esDescartado ? ' is-descartado' : '')},
      cabecera,
      el('p', {class: 'hist-item-meta', text: metaTexto(item)}),
      motivo,
      item.resumen ? el('p', {class: 'hist-item-resumen', text: item.resumen + (item.resumen.length >= 240 ? '…' : '')}) : null,
      acciones);
  }

  function botonEstado(item) {
    const publicar = item.estado !== 'publicado';
    return el('button', {
      class: 'btn btn-sm' + (publicar ? ' btn-primary' : ''),
      type: 'button',
      text: publicar ? 'Marcar como publicada' : 'Volver a borrador',
      onclick: ev => cambiarEstado(item, publicar ? 'publicado' : 'borrador', ev.currentTarget),
    });
  }

  async function cargarLista() {
    const lista = $('hist-lista');
    const pedido = ++estado.pedido;
    lista.setAttribute('aria-busy', 'true');
    $('hist-estado-carga').textContent = 'Cargando…';
    const params = new URLSearchParams({pagina: estado.pagina, por_pagina: POR_PAGINA});
    if (estado.q) params.set('q', estado.q);
    if (estado.seccion === 'generados_aprobados') params.set('estado', estado.filtroEstado);
    try {
      const r = await fetch(`/api/historial/${estado.seccion}?${params}`);
      const d = await r.json();
      if (pedido !== estado.pedido) return;
      if (!d.success) throw new Error(d.error || 'Error desconocido');
      lista.replaceChildren(...d.items.map(renderItem));
      const vacio = !d.items.length;
      $('hist-vacio').hidden = !vacio;
      $('hist-vacio').textContent = estado.q
        ? `No hay resultados para "${estado.q}".`
        : SECCIONES[estado.seccion].vacio;
      renderPaginacion(d);
      $('hist-estado-carga').textContent = vacio ? '' : `${fmtNum(d.total)} en total`;
    } catch (e) {
      if (pedido !== estado.pedido) return;
      lista.replaceChildren();
      $('hist-vacio').hidden = false;
      $('hist-vacio').textContent = 'No se pudo cargar el historial: ' + e.message;
      $('hist-paginacion').hidden = true;
      $('hist-estado-carga').textContent = '';
    } finally {
      if (pedido === estado.pedido) lista.removeAttribute('aria-busy');
    }
  }

  function renderPaginacion(d) {
    $('hist-paginacion').hidden = d.paginas <= 1;
    $('hist-pag-info').textContent = `Página ${d.pagina} de ${d.paginas}`;
    $('hist-pag-ant').disabled = d.pagina <= 1;
    $('hist-pag-sig').disabled = d.pagina >= d.paginas;
  }

  function irAPagina(delta) {
    estado.pagina = Math.max(1, estado.pagina + delta);
    cargarLista();
    $('hist-panel').scrollIntoView({block: 'start', behavior: 'smooth'});
  }

  async function cambiarEstado(item, nuevo, boton) {
    boton.disabled = true;
    try {
      const r = await fetch('/api/historial/estado', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({coleccion: item.coleccion, id: item.id, estado: nuevo}),
      });
      const d = await r.json();
      if (!d.success) throw new Error(d.error);
      window.showToast?.(nuevo === 'publicado' ? 'Nota marcada como publicada' : 'Nota devuelta a borrador', 'success');
      await Promise.all([cargarResumen(), cargarLista()]);
      if (!$('modal-hist').hidden) abrirDetalle({...item, estado: nuevo}, false);
    } catch (e) {
      boton.disabled = false;
      window.showToast?.('No se pudo cambiar el estado: ' + e.message, 'error');
    }
  }

  // ── Detalle (diálogo) ─────────────────────────────────────────────────────
  let volverFoco = null;

  async function abrirDetalle(item, guardarFoco = true) {
    const dialogo = $('modal-hist');
    if (guardarFoco) volverFoco = document.activeElement;
    $('hist-det-titulo').textContent = item.titulo;
    $('hist-det-meta').textContent = metaTexto(item);
    $('hist-det-cuerpo').replaceChildren(el('p', {class: 'hist-muted', text: 'Cargando…'}));
    $('hist-det-acciones').replaceChildren();
    if (dialogo.hidden) abrirDialogo();
    try {
      const r = await fetch(`/api/historial/${item.seccion}/${item.coleccion}/${item.id}`);
      const d = await r.json();
      if (!d.success) throw new Error(d.error);
      const completo = d.item;
      const extra = [];
      if (completo.seccion === 'generados_aprobados') extra.push(badgeEstado(completo));
      if (completo.seccion.endsWith('descartados')) {
        extra.push(el('p', {class: 'hist-motivo' + (completo.motivo ? '' : ' is-desconocido')},
          el('strong', {text: 'Motivo del descarte: '}), completo.motivo || 'no registrado'));
      }
      $('hist-det-meta').replaceChildren(el('span', {text: metaTexto(completo)}), ...extra);
      renderContenido($('hist-det-cuerpo'), completo);
      const acciones = [
        completo.seccion === 'generados_aprobados' ? botonEstado(completo) : null,
        esLinkSeguro(completo.url)
          ? el('a', {class: 'btn', href: completo.url, target: '_blank', rel: 'noopener noreferrer', text: 'Abrir fuente ↗'})
          : null,
        el('button', {class: 'btn', type: 'button', text: 'Copiar texto', onclick: () => {
          navigator.clipboard?.writeText(completo.contenido || '');
          window.showToast?.('Texto copiado', 'success');
        }}),
      ];
      // append() convertiría un null en el texto "null": se filtran antes.
      $('hist-det-acciones').append(...acciones.filter(Boolean));
    } catch (e) {
      $('hist-det-cuerpo').replaceChildren(el('p', {class: 'hist-muted', text: 'No se pudo cargar: ' + e.message}));
    }
  }

  function abrirDialogo() {
    const dialogo = $('modal-hist');
    dialogo.hidden = false;
    dialogo.classList.add('open');
    for (const sel of ['.app-container', '.workspace-nav', '#execution-dock']) {
      const n = document.querySelector(sel);
      if (n) n.inert = true;
    }
    dialogo.querySelector('.modal-close').focus();
  }

  function cerrarDetalle() {
    const dialogo = $('modal-hist');
    if (dialogo.hidden) return;
    dialogo.hidden = true;
    dialogo.classList.remove('open');
    for (const sel of ['.app-container', '.workspace-nav', '#execution-dock']) {
      const n = document.querySelector(sel);
      if (n) n.inert = false;
    }
    if (volverFoco && volverFoco.isConnected) volverFoco.focus();
  }

  // ── Eventos ───────────────────────────────────────────────────────────────
  function iniciar() {
    const tabs = $('hist-tabs');
    if (!tabs) return;

    tabs.querySelectorAll('[role="tab"]').forEach(tab =>
      tab.addEventListener('click', () => seleccionarSeccion(tab.dataset.seccion)));
    tabs.addEventListener('keydown', ev => {
      const orden = Object.keys(SECCIONES);
      const i = orden.indexOf(estado.seccion);
      const destino = {ArrowRight: orden[(i + 1) % orden.length], ArrowLeft: orden[(i - 1 + orden.length) % orden.length],
        Home: orden[0], End: orden[orden.length - 1]}[ev.key];
      if (!destino) return;
      ev.preventDefault();
      seleccionarSeccion(destino, true);
    });

    let espera;
    $('hist-buscar').addEventListener('input', ev => {
      clearTimeout(espera);
      espera = setTimeout(() => {
        estado.q = ev.target.value.trim();
        estado.pagina = 1;
        cargarLista();
      }, 300);
    });

    $('hist-filtro-estado').addEventListener('change', ev => {
      estado.filtroEstado = ev.target.value;
      estado.pagina = 1;
      cargarLista();
    });

    $('hist-refrescar').addEventListener('click', () => { cargarResumen(); cargarLista(); });
    $('hist-pag-ant').addEventListener('click', () => irAPagina(-1));
    $('hist-pag-sig').addEventListener('click', () => irAPagina(1));

    const dialogo = $('modal-hist');
    dialogo.addEventListener('click', ev => { if (ev.target === dialogo) cerrarDetalle(); });
    dialogo.querySelectorAll('[data-cerrar]').forEach(b => b.addEventListener('click', cerrarDetalle));
    dialogo.addEventListener('keydown', ev => {
      if (ev.key === 'Escape') { ev.preventDefault(); cerrarDetalle(); return; }
      if (ev.key !== 'Tab') return;
      const focos = [...dialogo.querySelectorAll('button, a[href], [tabindex="0"]')]
        .filter(n => !n.disabled && n.getClientRects().length);
      const primero = focos[0], ultimo = focos[focos.length - 1];
      if (ev.shiftKey && document.activeElement === primero) { ev.preventDefault(); ultimo.focus(); }
      if (!ev.shiftKey && document.activeElement === ultimo) { ev.preventDefault(); primero.focus(); }
    });

    // Se carga recién al abrir la vista: no hace falta pegarle a la base
    // en cada visita al dashboard si nadie mira el historial.
    document.addEventListener('workspace:open', ev => {
      if (ev.detail !== 'historial') return;
      cargarResumen();
      if (!estado.cargado) { estado.cargado = true; seleccionarSeccion(estado.seccion); }
      else cargarLista();
    });
    if (location.hash === '#historial') {
      document.dispatchEvent(new CustomEvent('workspace:open', {detail: 'historial'}));
    }
  }

  iniciar();
})();
