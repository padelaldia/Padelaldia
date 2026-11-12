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

  // Si es una petición POST, intentamos actualizar (requiere contraseña de admin)
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

      // Simulamos el envío del formulario con los parámetros que la FCP suele procesar
      const formData = new URLSearchParams();
      formData.append('ano', '2026');
      formData.append('ctl00$ContentPlaceHolder1$ddlAno', '2026'); // Parámetro común ASP.NET si aplica

      const resp = await fetch(START_URL, { method: 'POST', headers, body: formData.toString() });
      const buffer = await resp.arrayBuffer();
      const decoder = new TextDecoder('iso-8859-1');
      const htmlMain = decoder.decode(buffer);

      const teams = [];
      const seen = new Set();
      const leagueLinks = [];
      
      // Búsqueda más flexible de enlaces de ligas o grupos
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

      // Si no encuentra enlaces específicos de fases, forzamos la URL principal como objetivo
      const targetUrls = leagueLinks.length > 0 ? leagueLinks : [{ name: 'Liga Cántabra General', url: START_URL }];

      for (const league of targetUrls) {
        try {
          const leagueResp = await fetch(league.url, { headers });
          const leagueHtml = decoder.decode(await leagueResp.arrayBuffer());
          
          // Regex mejorada para capturar nombres de equipos en tablas o enlaces internos
          const teamRegex = /<a[^>]*href=["']([^"']*(?:Equipo|Calendario|Clasificacion|Club)[^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
          let tMatch;
          
          while ((tMatch = teamRegex.exec(leagueHtml)) !== null) {
            const rawName = tMatch[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
            if (!rawName || rawName.length < 3) continue;
            
            // Filtramos palabras comunes que no son nombres de equipos
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

      // Actualizamos la caché del servidor solo si se encontraron equipos nuevos, o mantenemos los anteriores
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
      return res.status(500).json({ ok: false, error: err.message });
    }
  }

  // Petición GET normal para los usuarios
  return res.status(200).json({
    ok: true,
    updatedAt: cachedData.updatedAt || new Date().toISOString(),
    teamsCount: cachedData.teams.length,
    teams: cachedData.teams
  });
}
