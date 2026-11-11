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
    // Simulamos el envío del formulario eligiendo el año 2026
    const formData = new URLSearchParams();
    formData.append('ano', '2026');

    const resp = await fetch(START_URL, {
      method: 'POST',
      headers,
      body: formData.toString()
    });

    const buffer = await resp.arrayBuffer();
    const decoder = new TextDecoder('iso-8859-1');
    const html = decoder.decode(buffer);

    const teams = [];
    const seen = new Set();

    // Extraer cualquier enlace o texto que represente equipos o divisiones en el año 2026
    const anchorRegex = /<a[^>]*href=["']([^"']*(?:Equipo|Calendario|Clasificacion|Liga)[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
    let m;
    while ((m = anchorRegex.exec(html)) !== null) {
      const href = m[1].trim();
      const rawName = m[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
      
      if (!rawName || rawName.length < 3) continue;
      if (/^(ver|calendario|clasificaci|resultados|volver|inicio|siguiente|anterior|2026|2025|2024)/i.test(rawName)) continue;

      const key = rawName.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);

      teams.push({
        id: Buffer.from(key).toString('base64').replace(/=/g, ''),
        name: rawName,
        category: 'Liga Cántabra 2026',
        categoryId: '2026',
        detailUrl: href.startsWith('http') ? href : `${BASE_URL}/${href.replace(/^\//, '')}`
      });
    }

    return res.status(200).json({
      ok: true,
      source: START_URL,
      updatedAt: new Date().toISOString(),
      teamsCount: teams.length,
      teams
    });

  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
}
