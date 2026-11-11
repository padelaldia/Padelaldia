export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  res.setHeader('Cache-Control', 's-maxage=1800, stale-while-revalidate');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const BASE_URL = 'https://federacioncantabradepadel.com';
  const START_URL = `${BASE_URL}/Liga_ListadoEquipos?`;

  const headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9'
  };

  try {
    const { action, id, teamId, url } = req.query;

    // 1. Obtener todas las categorías/divisiones disponibles y sus equipos
    if (!action || action === 'all') {
      const mainResp = await fetch(START_URL, { headers });
      const mainHtml = await mainResp.text();

      // Extraer opciones de categorías/grupos del desplegable (<select>) o enlaces con Id=
      const categories = [];
      const optionRegex = /<option[^>]*value=["']?(\d+)["']?[^>]*>([\s\S]*?)<\/option>/gi;
      let match;
      while ((match = optionRegex.exec(mainHtml)) !== null) {
        const val = match[1].trim();
        const label = match[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
        if (val && val !== '0' && label && !categories.some(c => c.id === val)) {
          categories.push({ id: val, name: label });
        }
      }

      // Buscar también enlaces tipo Liga_ListadoEquipos?Id=XXXX por si vienen como pestañas o links
      const linkRegex = /Liga_ListadoEquipos\?Id=(\d+)[^>]*>([\s\S]*?)<\/a>/gi;
      while ((match = linkRegex.exec(mainHtml)) !== null) {
        const val = match[1].trim();
        const label = match[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
        if (val && label && !categories.some(c => c.id === val)) {
          categories.push({ id: val, name: label });
        }
      }

      // Si no detecta desplegable, analizar la propia página principal
      if (categories.length === 0) {
        categories.push({ id: 'default', name: 'Liga Cántabra' });
      }

      // Extraer todos los equipos de cada categoría en paralelo
      const results = await Promise.all(
        categories.map(async (cat) => {
          try {
            const targetUrl = cat.id === 'default' ? START_URL : `${BASE_URL}/Liga_ListadoEquipos?Id=${cat.id}`;
            const html = cat.id === 'default' ? mainHtml : await (await fetch(targetUrl, { headers })).text();
            const teams = parseTeamsFromHtml(html, cat.name, cat.id, BASE_URL);
            return teams;
          } catch (e) {
            return [];
          }
        })
      );

      const allTeams = results.flat();
      return res.status(200).json({
        ok: true,
        source: START_URL,
        updatedAt: new Date().toISOString(),
        categoriesCount: categories.length,
        categories,
        teamsCount: allTeams.length,
        teams: allTeams
      });
    }

    // 2. Obtener detalle de calendario y resultados de un equipo o categoría concreta
    if (action === 'detail' && (url || id)) {
      const target = url ? (url.startsWith('http') ? url : `${BASE_URL}/${url.replace(/^\//, '')}`) : `${BASE_URL}/Liga_Calendario?Id=${id}`;
      const resp = await fetch(target, { headers });
      const html = await resp.text();
      return res.status(200).json({ ok: true, target, rawLength: html.length, html });
    }

    return res.status(400).json({ ok: false, error: 'Parámetro action no válido' });
  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
}

function parseTeamsFromHtml(html, categoryName, categoryId, baseUrl) {
  const teams = [];
  const seen = new Set();

  // Buscar filas de tablas o enlaces a fichas de equipo (Liga_Equipo, Liga_Calendario, etc.)
  const anchorRegex = /<a[^>]*href=["']([^"']*(?:Equipo|Calendario|Clasificacion)[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = anchorRegex.exec(html)) !== null) {
    const href = m[1].trim();
    const rawName = m[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
    if (!rawName || rawName.length < 2) continue;
    if (/^(ver|calendario|clasificaci|resultados|volver|inicio|siguiente|anterior)/i.test(rawName)) continue;

    const key = `${categoryId}::${rawName.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);

    teams.push({
      id: Buffer.from(key).toString('base64').replace(/=/g, ''),
      name: rawName,
      category: categoryName,
      categoryId,
      detailUrl: href.startsWith('http') ? href : `${baseUrl}/${href.replace(/^\//, '')}`
    });
  }

  return teams;
}
