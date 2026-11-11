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
    'Accept-Language': 'es-ES,es;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded'
  };

  try {
    const decoder = new TextDecoder('iso-8859-1');

    // 1. Obtener la página principal seleccionando el año 2026
    const formData = new URLSearchParams();
    formData.append('ano', '2026');

    const resp = await fetch(START_URL, {
      method: 'POST',
      headers,
      body: formData.toString()
    });
    const htmlMain = decoder.decode(await resp.arrayBuffer());

    const teams = [];
    const seen = new Set();

    // 2. Encontrar los enlaces de las ligas principales (ej. Liga_previo?id=...)
    const leagueLinks = [];
    const leagueRegex = /<a[^>]*href=["']([^"']*Liga_previo[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
    let match;
    while ((match = leagueRegex.exec(htmlMain)) !== null) {
      const href = match[1].trim();
      const name = match[2].replace(/<[^>]+>/g, '').trim();
      const fullUrl = href.startsWith('http') ? href : `${BASE_URL}/${href.replace(/^\//, '')}`;
      if (!leagueLinks.some(l => l.url === fullUrl)) {
        leagueLinks.push({ name, url: fullUrl });
      }
    }

    // Si no encuentra enlaces directos de liga, probamos a raspar la misma página principal
    const targetUrls = leagueLinks.length > 0 ? leagueLinks : [{ name: 'Liga Cántabra', url: START_URL }];

    // 3. Entrar en cada sección de liga para extraer los equipos
    for (const league of targetUrls) {
      try {
        const leagueResp = await fetch(league.url, { headers });
        const leagueHtml = decoder.decode(await leagueResp.arrayBuffer());

        // Buscar nombres de equipos en tablas o enlaces internos de equipos
        const teamRegex = /<a[^>]*href=["']([^"']*(?:Equipo|Calendario|Clasificacion)[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
        let tMatch;
        while ((tMatch = teamRegex.exec(leagueHtml)) !== null) {
          const rawName = tMatch[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
          if (!rawName || rawName.length < 3) continue;
          if (/^(ver|calendario|clasificaci|resultados|volver|inicio|siguiente|anterior|2026|liga)/i.test(rawName)) continue;

          const key = `${league.name}::${rawName.toLowerCase()}`;
          if (seen.has(key)) continue;
          seen.add(key);

          teams.push({
            id: Buffer.from(key).toString('base64').replace(/=/g, ''),
            name: rawName,
            category: league.name,
            categoryId: '2026'
          });
        }
      } catch (e) {
        // Ignorar errores individuales de sub-enlaces y continuar
      }
    }

    return res.status(200).json({
      ok: true,
      source: START_URL,
      updatedAt: new Date().toISOString(),
      leaguesFound: targetUrls.length,
      teamsCount: teams.length,
      teams
    });

  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
}
