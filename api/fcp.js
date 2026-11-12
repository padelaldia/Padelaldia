// Memoria caché temporal en el servidor para los usuarios
let cachedData = {
  updatedAt: null,
  teams: []
};

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();

  if (req.method === 'POST') {
    const { password } = req.body || {};
    const ADMIN_SECRET = process.env.ADMIN_SECRET || 'padel2026';

    if (password !== ADMIN_SECRET) {
      return res.status(401).json({ ok: false, error: 'Contraseña de administrador incorrecta.' });
    }

    try {
      const BASE_URL = 'https://www.federacioncantabradepadel.com';
      const START_URL = `${BASE_URL}/Liga_ListadoEquipos`;
      const headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': BASE_URL
      };

      const formData = new URLSearchParams();
      formData.append('ano', '2026');

      console.log(`[SCRAPER] Realizando petición POST a: ${START_URL}`);
      const resp = await fetch(START_URL, { method: 'POST', headers, body: formData.toString() });
      
      console.log(`[SCRAPER] Código de estado HTTP recibido: ${resp.status} ${resp.statusText}`);

      const buffer = await resp.arrayBuffer();
      const decoder = new TextDecoder('iso-8859-1');
      const htmlMain = decoder.decode(buffer);

      console.log('[SCRAPER] Extracto del HTML recibido:', htmlMain.substring(0, 400));

      const teams = [];
      const seen = new Set();
      const leagueLinks = [];
      
      const leagueRegex = /<a[^>]*href=["']([^"']*(?:Liga_previo|grupo|categoria|fase)[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
      let match;
      
      while ((match = leagueRegex.exec(htmlMain)) !== null) {
        const href = match[1].trim();
        const name = match[2].replace(/<[^>]+>/g, '').trim();
        const fullUrl = href.startsWith('http') ? href : `${BASE_URL}/${href.replace(/^\//, '')}`;
        if (!leagueLinks.some(l => l.url === fullUrl)) {
          leagueLinks.push({ name: name || 'Liga Cántabra', url: fullUrl });
        }
      }

      console.log(`[SCRAPER] Enlaces de ligas encontrados: ${leagueLinks.length}`);

      const targetUrls = leagueLinks.length > 0 ? leagueLinks : [{ name: 'Liga Cántabra General', url: START_URL }];

      for (const league of targetUrls) {
        try {
          const leagueResp = await fetch(league.url, { headers });
          const leagueHtml = decoder.decode(await leagueResp.arrayBuffer());
          
          const teamRegex = /<a[^>]*href=["']([^"']*(?:Equipo|Calendario|Clasificacion|Club)[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
          let tMatch;
          
          while ((tMatch = teamRegex.exec(leagueHtml)) !== null) {
            const rawName = tMatch[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
            if (!rawName || rawName.length < 3) continue;
            if (/^(ver|calendario|clasificaci|resultados|volver|inicio|siguiente|anterior|2026|liga|grupo|fase|club|página)/i.test(rawName)) continue;

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
          console.error(`Error procesando liga ${league.name}:`, e.message);
        }
      }

      console.log(`[SCRAPER] Total de equipos únicos extraídos: ${teams.length}`);

      cachedData = {
        updatedAt: new Date().toISOString(),
        teams: teams.length > 0 ? teams : cachedData.teams
      };

      return res.status(200).json({ 
        ok: true, 
        message: 'Sincronización completada', 
        teamsCount: cachedData.teams.length, 
        updatedAt: cachedData.updatedAt 
      });

    } catch (err) {
      console.error('[SCRAPER ERROR CRÍTICO]:', err.message);
      return res.status(500).json({ ok: false, error: err.message });
    }
  }

  return res.status(200).json({
    ok: true,
    updatedAt: cachedData.updatedAt || new Date().toISOString(),
    teamsCount: cachedData.teams.length,
    teams: cachedData.teams
  });
}
