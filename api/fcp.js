export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');

  if (req.method === 'OPTIONS') return res.status(200).end();

  const BASE_URL = 'https://federacioncantabradepadel.com';
  const START_URL = `${BASE_URL}/Liga_ListadoEquipos?`;

  const headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9'
  };

  try {
    const resp = await fetch(START_URL, { headers });
    // Decodificar correctamente tildes y eñes (Windows-1252 / ISO-8859-1 típico de federaciones)
    const buffer = await resp.arrayBuffer();
    const decoder = new TextDecoder('iso-8859-1');
    const html = decoder.decode(buffer);

    // 1. Buscar todos los desplegables (<select>) de la página para ver qué filtros tiene
    const selects = [];
    const selectRegex = /<select[^>]*name=["']([^"']+)["'][^>]*>([\s\S]*?)<\/select>/gi;
    let sMatch;
    while ((sMatch = selectRegex.exec(html)) !== null) {
      const selectName = sMatch[1];
      const optionsHtml = sMatch[2];
      const options = [];
      const optRegex = /<option[^>]*value=["']?([^"'>]*)["']?[^>]*>([\s\S]*?)<\/option>/gi;
      let oMatch;
      while ((oMatch = optRegex.exec(optionsHtml)) !== null) {
        options.push({
          value: oMatch[1].trim(),
          text: oMatch[2].replace(/<[^>]+>/g, '').trim()
        });
      }
      selects.push({ name: selectName, options });
    }

    // 2. Buscar cualquier fila de tabla (<tr>) que parezca contener equipos
    const tableRows = [];
    const trRegex = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    let trMatch;
    while ((trMatch = trRegex.exec(html)) !== null) {
      const rowText = trMatch[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
      if (rowText.length > 3 && rowText.length < 200) {
        tableRows.push(rowText);
      }
    }

    return res.status(200).json({
      ok: true,
      selectsCount: selects.length,
      selects,
      sampleRowsCount: tableRows.length,
      sampleRows: tableRows.slice(0, 25) // Muestra las primeras 25 filas detectadas
    });

  } catch (err) {
    return res.status(500).json({ ok: false, error: err.message });
  }
}
