import express, { Request, Response } from 'express';
import axios, { AxiosError } from 'axios';
import http from 'http';
import path from 'path';

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const SCRAPERS_URL = process.env.SCRAPERS_URL || 'http://localhost:5000';

const VALID_SPIDERS = ['lanacion', 'aftermarket', 'ambito', 'cenital', 'perfil'] as const;
type Spider = typeof VALID_SPIDERS[number];

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

function extraerError(err: unknown): string {
  const axiosErr = err as AxiosError<{ error?: string; output?: string }>;
  return (
    axiosErr.response?.data?.error ||
    axiosErr.response?.data?.output ||
    'No se pudo conectar con el servicio de scrapers.'
  );
}

// ── Endpoints JSON (sin streaming, compatibilidad) ──────────────────────────

app.post('/api/run/:spider', async (req: Request, res: Response): Promise<void> => {
  const spider = req.params.spider as Spider;
  if (!(VALID_SPIDERS as readonly string[]).includes(spider)) {
    res.status(400).json({ success: false, error: `Spider '${spider}' no existe.` });
    return;
  }
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/run/${spider}`, {}, { timeout: 660_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.post('/api/run-all', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/run-all`, {}, { timeout: 1_800_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.post('/api/generar', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/generar`, req.body, { timeout: 660_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.get('/api/ultimo-articulo', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/ultimo-articulo`, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    const axiosErr = err as AxiosError<{ error?: string }>;
    if (axiosErr.response?.status === 404) {
      res.status(404).json({ success: false, error: 'Todavía no hay artículos generados.' });
      return;
    }
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.get('/api/health', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/health`, { timeout: 5_000 });
    res.json({ express: 'ok', scrapers: data });
  } catch {
    res.json({ express: 'ok', scrapers: 'unreachable' });
  }
});

// ── Endpoints streaming (proxy directo sin buffering) ───────────────────────

function crearProxyStreaming(rutaFlask: string) {
  return (req: Request, res: Response): void => {
    const parsed = new URL(SCRAPERS_URL);

    const opts: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || 5000,
      path: rutaFlask,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    };

    const proxyReq = http.request(opts, (proxyRes) => {
      res.status(proxyRes.statusCode || 200);
      res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('X-Accel-Buffering', 'no');
      proxyRes.pipe(res);
    });

    proxyReq.on('error', () => {
      res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
    });

    proxyReq.write(JSON.stringify({}));
    proxyReq.end();
  };
}

app.post('/api/stream/run/:spider', (req: Request, res: Response) => {
  const spider = req.params.spider as Spider;
  if (!(VALID_SPIDERS as readonly string[]).includes(spider)) {
    res.status(400).json({ success: false, error: `Spider '${spider}' no existe.` });
    return;
  }
  crearProxyStreaming(`/stream/run/${spider}`)(req, res);
});

app.post('/api/stream/run-all', crearProxyStreaming('/stream/run-all'));

app.post('/api/stream/generar', (req: Request, res: Response) => {
  const parsed = new URL(SCRAPERS_URL);
  const payload = JSON.stringify(req.body || {});
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/stream/generar',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => {
    res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
  });
  proxyReq.write(payload);
  proxyReq.end();
});

// ── Nuevos endpoints de la API Flask ──────────────────────────────────────

// GET /api/check-volume
app.get('/api/check-volume', async (req: Request, res: Response): Promise<void> => {
  try {
    const kw = req.query.keyword || '';
    const { data } = await axios.get(`${SCRAPERS_URL}/api/check-volume?keyword=${encodeURIComponent(String(kw))}`, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/add-url
app.post('/api/add-url', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/add-url`, req.body, { timeout: 300_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// GET /api/scraping-config
app.get('/api/scraping-config', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/scraping-config`, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/scraping-config
app.post('/api/scraping-config', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/scraping-config`, req.body, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// GET /api/providers
app.get('/api/providers', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/providers`, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/providers
app.post('/api/providers', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/providers`, req.body, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/run-automation
app.post('/api/run-automation', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/run-automation`, {}, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/stream/run-automation
app.post('/api/stream/run-automation', (req: Request, res: Response) => {
  const parsed = new URL(SCRAPERS_URL);
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/api/stream/run-automation',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => {
    res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
  });
  proxyReq.write(JSON.stringify({}));
  proxyReq.end();
});

// GET /api/trusted-urls-stats
app.get('/api/trusted-urls-stats', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/trusted-urls-stats`, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/discover-sources
app.post('/api/discover-sources', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/discover-sources`, {}, { timeout: 300_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// GET /api/suggested-urls
app.get('/api/suggested-urls', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/suggested-urls`, { timeout: 10_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/evaluate-article
app.post('/api/evaluate-article', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/evaluate-article`, req.body, { timeout: 60_000 });
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

// POST /api/stream/add-url
app.post('/api/stream/add-url', (req: Request, res: Response) => {
  const parsed = new URL(SCRAPERS_URL);
  const payload = JSON.stringify(req.body);
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/stream/add-url',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => {
    res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
  });
  proxyReq.write(payload);
  proxyReq.end();
});

// ── Endpoints para URLs custom ─────────────────────────────────────────────

app.post('/api/run-custom', async (req: Request, res: Response): Promise<void> => {
  const { urls, max, modo } = req.body;
  if (!urls || !Array.isArray(urls) || urls.length === 0) {
    res.status(400).json({ success: false, error: 'Lista de URLs vacía.' });
    return;
  }
  try {
    const { data } = await axios.post(
      `${SCRAPERS_URL}/run-custom`,
      { urls, max: max || 5, modo: modo || 'list' },
      { timeout: 660_000 }
    );
    res.json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: extraerError(err) });
  }
});

app.post('/api/stream/run-custom', (req: Request, res: Response) => {
  const { urls, max, modo } = req.body;
  if (!urls || !Array.isArray(urls) || urls.length === 0) {
    res.status(400).json({ success: false, error: 'Lista de URLs vacía.' });
    return;
  }
  const parsed = new URL(SCRAPERS_URL);
  const payload = JSON.stringify({ urls, max: max || 5, modo: modo || 'list' });
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/stream/run-custom',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => {
    res.status(500).json({ success: false, error: 'No se pudo conectar con el servicio de scrapers.' });
  });
  proxyReq.write(payload);
  proxyReq.end();
});

// ── Fase 2 endpoints ──────────────────────────────────────────────────────────

app.get('/api/fase2/categorias', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/fase2/categorias`, { timeout: 10_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.get('/api/fase2/regiones', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/fase2/regiones`, { timeout: 10_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.post('/api/fase2/scrape', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/fase2/scrape`, req.body, { timeout: 300_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.post('/api/fase2/stream/scrape', (req: Request, res: Response) => {
  const parsed = new URL(SCRAPERS_URL);
  const payload = JSON.stringify(req.body || {});
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/api/fase2/stream/scrape',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => res.status(500).json({ success: false, error: 'Sin conexión con scrapers.' }));
  proxyReq.write(payload);
  proxyReq.end();
});

app.get('/api/fase2/clientes', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/fase2/clientes`, { timeout: 10_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.post('/api/fase2/clientes', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/fase2/clientes`, req.body, { timeout: 10_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.delete('/api/fase2/clientes/:slug', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.delete(`${SCRAPERS_URL}/api/fase2/clientes/${req.params.slug}`, { timeout: 10_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.post('/api/fase2/generar', async (req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.post(`${SCRAPERS_URL}/api/fase2/generar`, req.body, { timeout: 1_800_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

app.post('/api/fase2/stream/generar', (req: Request, res: Response) => {
  const parsed = new URL(SCRAPERS_URL);
  const payload = JSON.stringify(req.body || {});
  const opts: http.RequestOptions = {
    hostname: parsed.hostname,
    port: parsed.port || 5000,
    path: '/api/fase2/stream/generar',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) },
  };
  const proxyReq = http.request(opts, (proxyRes) => {
    res.status(proxyRes.statusCode || 200);
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    proxyRes.pipe(res);
  });
  proxyReq.on('error', () => res.status(500).json({ success: false, error: 'Sin conexión con scrapers.' }));
  proxyReq.write(payload);
  proxyReq.end();
});

app.get('/api/fase2/ultima-nota', async (_req: Request, res: Response): Promise<void> => {
  try {
    const { data } = await axios.get(`${SCRAPERS_URL}/api/fase2/ultima-nota`, { timeout: 10_000 });
    res.json(data);
  } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
});

for (const ruta of ['/api/fase2/notas', '/api/fase2/notas/:id']) {
  app.get(ruta, async (req: Request, res: Response): Promise<void> => {
    try {
      const { data } = await axios.get(`${SCRAPERS_URL}${req.path}`, { timeout: 10_000 });
      res.json(data);
    } catch (err) { res.status(500).json({ success: false, error: extraerError(err) }); }
  });
}

// ── Inicio ──────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`Express corriendo en http://localhost:${PORT}`);
  console.log(`Scrapers service: ${SCRAPERS_URL}`);
});
