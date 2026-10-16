# AGENTS.md

## Acceso a servicios de Google

### Google Drive ✅
- **Estado:** Habilitado y funcionando
- **Permisos:** Lectura/escritura completa (Drive, Docs, Sheets, Slides, Calendar)
- **Token:** `C:\Users\Manuel\.config\google-drive-mcp\tokens.json`
- **Proyecto Google Cloud:** 796384769588

### Gmail ✅
- **Estado:** Habilitado y funcionando
- **Permisos:** Lectura/escritura completa (enviar, leer, buscar, eliminar, gestionar etiquetas y filtros)

### Acciones disponibles con Google Drive
- Listar archivos y carpetas
- Leer documentos de Google Docs
- Leer hojas de cálculo de Google Sheets
- Leer presentaciones de Google Slides
- Descargar archivos (PDFs, imágenes, etc.)
- Crear, editar y eliminar archivos
- Gestionar permisos de archivos
- Crear y gestionar eventos de Google Calendar

### Acciones disponibles con Gmail
- Leer correos electrónicos
- Enviar correos electrónicos
- Buscar correos
- Eliminar correos
- Gestionar etiquetas (crear, modificar, eliminar)
- Gestionar filtros (crear, modificar, eliminar)
- Descargar adjuntos
- Crear borradores
- Modificar etiquetas de mensajes (mover a carpetas)

## Agentes y Comandos

### Agentes disponibles
- **scrapling-runner**: Sincroniza specs desde Drive y ejecuta el pipeline de scraping

### Comandos disponibles
- **/sync-cerebro**: Sincroniza la memoria del proyecto desde Drive y codea en base a eso
  - Carpeta Drive ID: `1Mlk84ZWPhkUfwKps0pLI_H6Utf_e73iY4NrRScNUEHE`
  - Uso: `/sync-cerebro` o `opencode run --agent scrapling-runner "/sync-cerebro"`

## Specs desde Drive (sincronizado)

### Proyecto: AfterDrive / Vloger
- **Objetivo:** Automatización de contenidos inteligentes para el sector automotriz y postventa

### Arquitectura de IA (Recomendada)
- **Opción elegida:** Arquitectura híbrida con Ollama + modelos locales
- **Razón:** Control de costos, privacidad, resiliencia frente a fallos de APIs externas
- **Modelo local:** Ollama con modelos open source (Llama 3.2, Gemma 3, Mistral NeMo)

### Pipeline del proyecto
1. **Extracción y Validación** (1-2 semanas)
   - Scraper inteligente (Python) + Validador local (Ollama)
   - Filtra noticias irrelevantes, detecta paywalls, evita duplicados
   - MongoDB con estructura de "notas crudas"

2. **Cerebro Multi-Agente** (2-3 semanas)
   - Orquestador de IA con 5 personalidades (Técnico, Informal, Negocios, Entusiasta, Institucional)
   - Generación automática de versiones y validación post-escritura

3. **Ecosistema Docker & Web** (3-4 semanas)
   - Contenedores para todo el sistema
   - Panel de administración (Next.js) para aprobar/editar/rechazar vlogs

4. **Automatización de Fuentes** (2 semanas)
   - RSS, Sitemaps, asistencia de IA para detectar estructuras web
   - Reducir tiempo de alta de nuevas fuentes de 4h a 30min

5. **Generador Comercial (Alephee)** (3 semanas)
   - Vlogs basados en formularios de clientes
   - Combina noticias reales con productos del cliente

6. **Conector HubSpot** (2-3 semanas)
   - Publicación automática en CMS de AfterDrive vía API

### Costos estimados
- **Por ejecución:** $0.03 - $0.15 (normal), $0.20 - $0.50 (pesado)
- **Mensual (10 ejecuciones/día):** $20 - $45 (normal), $60 - $150 (pesado)
- **Optimización:** Resumir antes de pasar entre etapas, usar JSON estructurado, batching

### Stack tecnológico actual
- **Scraping:** Scrapling (Python)
- **Base de datos:** MongoDB Atlas
- **IA local:** LM Studio / Ollama
- **Frontend:** dashboard HTML servido por Flask/Python (con login)
- **Origen specs:** Google Drive (ID: `1Mlk84ZWPhkUfwKps0pLI_H6Utf_e73iY4NrRScNUEHE`)

### Última corrida
*2026-07-11: Sincronización inicial desde Drive. Specs cargadas correctamente.*
*2026-07-11: Scraping ejecutado (aftermarketinternational + lacasadelrenault). 20 artículos nuevos. LM Studio no disponible (modo degradado). Mail de resumen enviado.*
