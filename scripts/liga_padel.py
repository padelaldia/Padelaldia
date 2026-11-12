#!/usr/bin/env python3
"""
Extrae equipos, clasificación y calendario/resultados de la Liga Cántabra de Pádel
(federacioncantabradepadel.com) y los guarda en CSV (separador ";", abren bien en Excel).

Uso:
    pip install requests beautifulsoup4
    python liga_padel.py                      # toda la liga (id 28942), ambos géneros, todas las fases y grupos
    python liga_padel.py --id 28942 --salida datos
    python liga_padel.py --file respuesta.html   # prueba offline con un HTML guardado (un solo grupo)

Genera en la carpeta de salida:
    partidos.csv, clasificacion.csv, equipos.csv
"""
import argparse
import csv
import datetime
import json
import os
import re
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

BASE = "https://www.federacioncantabradepadel.com/"
URL = BASE + "Liga_Calendario"
HEADERS = {"User-Agent": "Mozilla/5.0 (consulta personal de calendarios)"}
PAUSA = 1.0  # segundos entre peticiones, para no cargar el servidor


def limpiar(texto):
    return re.sub(r"\s+", " ", texto).strip()


def descargar(params, url=URL):
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "iso-8859-1"  # la web sirve en latin-1
    time.sleep(PAUSA)
    return r.text


def opciones(soup, select_id, excluir):
    sel = soup.find("select", id=select_id)
    if not sel:
        return []
    salida = []
    for o in sel.find_all("option"):
        v = o.get("value", "").strip()
        if v and v not in excluir:
            salida.append((v, limpiar(o.get_text())))
    return salida


def parsear(html, ctx):
    """Devuelve (partidos, clasificacion) de una página de grupo."""
    soup = BeautifulSoup(html, "html.parser")
    tablas = soup.select("div.table-responsive table")
    if len(tablas) < 2:
        return [], []
    cal, clas = tablas[0], tablas[1]

    # --- Calendario: matriz local (filas) x visitante (columnas) ---
    filas = cal.find_all("tr")
    cabecera = [limpiar(td.get_text()) for td in filas[0].find_all("td")][1:]
    por_jornada = max(len(cabecera) // 2, 1)
    partidos = []
    for fila in filas[1:]:
        tds = fila.find_all("td")
        if not tds:
            continue
        local = limpiar(tds[0].get_text())
        for visitante, td in zip(cabecera, tds[1:]):
            a = td.find("a", href=re.compile(r"partido="))
            if not a:
                continue  # celda vacía (diagonal)
            n = int(re.search(r"partido=(\d+)", a["href"]).group(1))
            estado = (td.get("class") or [""])[0]
            lineas = [limpiar(x) for x in a.get_text("\n").split("\n") if limpiar(x)]
            p = {
                **ctx,
                "partido": n,
                "jornada_aprox": (n - 1) // por_jornada + 1,
                "local": local,
                "visitante": visitante,
                "estado": estado,  # cercanos / confecha / cerrados / ultima / sinacta / sinvalidar
                "fecha_texto": "",
                "hora": "",
                "tandas": "",
                "lugar": "",
                "resultado": "",
            }
            primera = lineas[0] if lineas else ""
            if estado == "cerrados" or re.fullmatch(r"\d+/\d+", primera):
                # resultado ya jugado (también los "sin validar", con resultado provisional)
                p["resultado"] = primera
            elif estado == "confecha":
                m = re.match(r"(.+?)\s+(\d{1,2}:\d{2})$", lineas[0]) if lineas else None
                if m:
                    p["fecha_texto"], p["hora"] = m.group(1), m.group(2)
                elif lineas:
                    p["fecha_texto"] = lineas[0]
                for extra in lineas[1:]:
                    if extra.lower().startswith("tandas"):
                        p["tandas"] = extra.split(":", 1)[-1].strip()
                    else:
                        p["lugar"] = extra
            else:  # cercanos, ultima...: rango de fechas
                p["fecha_texto"] = lineas[0] if lineas else ""
            partidos.append(p)

    # --- Clasificación ---
    columnas = ["posicion", "equipo", "enfrentamientos", "puntos", "partidos_disputados",
                "partidos_ganados", "sets_favor", "sets_contra", "average_sets",
                "juegos_favor", "juegos_contra", "average_juegos"]
    clasif = []
    for fila in clas.find_all("tr", class_="lineas"):
        tds = [limpiar(td.get_text()) for td in fila.find_all("td")]
        if len(tds) < len(columnas):
            continue
        a = fila.find("a", href=re.compile(r"IdEquipo="))
        id_equipo = re.search(r"IdEquipo=(\d+)", a["href"]).group(1) if a else ""
        fila_d = dict(zip(columnas, tds))
        clasif.append({**ctx, "id_equipo": id_equipo, **fila_d})
    return partidos, clasif


def guardar(ruta, filas):
    if not filas:
        return
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(filas)
    print(f"  {ruta}: {len(filas)} filas")


def construir_json(partidos, clasif, liga_id, detalle=None):
    """Agrupa todo por equipo para que la web lo lea de una vez (data.json)."""
    detalle = detalle or {}
    categorias, equipos = {}, {}
    for c in clasif:
        categorias.setdefault(c["grupo_id"], {
            "id": c["grupo_id"], "name": c["grupo"],
            "genero": c["genero"], "fase": c["fase"]})
        equipos[(c["grupo_id"], c["equipo"])] = {
            "id": c["id_equipo"], "name": c["equipo"],
            "category": c["grupo"], "categoryId": c["grupo_id"],
            "genero": c["genero"], "fase": c["fase"],
            "position": int(c["posicion"]),
            "stats": {k: c[k] for k in (
                "enfrentamientos", "puntos", "partidos_disputados", "partidos_ganados",
                "sets_favor", "sets_contra", "average_sets",
                "juegos_favor", "juegos_contra", "average_juegos")},
            "matches": [],
        }

    for p in sorted(partidos, key=lambda x: (x["grupo_id"], x["partido"])):
        gol, gvis = None, None
        if p["resultado"] and "/" in p["resultado"]:
            a, b = p["resultado"].split("/", 1)
            gol, gvis = int(a), int(b)
        for propio, rival, es_local in ((p["local"], p["visitante"], True),
                                        (p["visitante"], p["local"], False)):
            eq = equipos.get((p["grupo_id"], propio))
            if not eq:
                continue
            m = {
                "partido": p["partido"], "jornada": p["jornada_aprox"],
                "home": es_local, "rival": rival, "estado": p["estado"],
                "date": p["fecha_texto"], "time": p["hora"],
                "tandas": p["tandas"], "sede": p["lugar"],
                "result": p["resultado"],
                "for": None if gol is None else (gol if es_local else gvis),
                "against": None if gol is None else (gvis if es_local else gol),
            }
            d = detalle.get(f"{p['grupo_id']}:{p['partido']}")
            if d:  # enfrentamiento ya jugado: fecha real, sets y juegos
                sl, sv = d["sets_local"], d["sets_visitante"]
                jl, jv = d["juegos_local"], d["juegos_visitante"]
                m.update({
                    "dateIso": d["fecha_iso"],
                    "time": d["hora"] or m["time"],
                    "sede": d["lugar"] or m["sede"],
                    "tandas": d["tandas"] or m["tandas"],
                    "setsFor": sl if es_local else sv, "setsAgainst": sv if es_local else sl,
                    "gamesFor": jl if es_local else jv, "gamesAgainst": jv if es_local else jl,
                })
            eq["matches"].append(m)
    return {
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "ligaId": liga_id,
        "categories": list(categorias.values()),
        "teams": list(equipos.values()),
    }


MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def a_entero(texto):
    m = re.search(r"-?\d+", (texto or "").replace(".", ""))
    return int(m.group()) if m else 0


def parsear_fecha(texto):
    """'domingo, 25 de octubre de 2026 - 10:00' -> ('2026-10-25', '10:00')."""
    m = re.search(r"(\d{1,2}) de (\w+) de (\d{4})(?:\s*-\s*(\d{1,2}:\d{2}))?", texto or "", re.I)
    if not m or m.group(2).lower() not in MESES:
        return "", ""
    iso = f"{int(m.group(3)):04d}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return iso, m.group(4) or ""


def parsear_resultado(html):
    """Página Liga_Resultado: cabecera del enfrentamiento y las 5 parejas con sus jugadores."""
    soup = BeautifulSoup(html, "html.parser")
    vals = [limpiar(i.get("value", "")) for i in soup.select("input.form-control")]
    if len(vals) < 12:
        return None
    (jornada, fecha, lugar, tandas, local, visitante,
     juegos_l, sets_l, part_l, part_v, sets_v, juegos_v) = vals[:12]
    fecha_iso, hora = parsear_fecha(fecha)

    filas = soup.select("tr.lineas")
    parejas = []
    i = 0
    while i < len(filas):
        a = [limpiar(td.get_text()) for td in filas[i].find_all("td")]
        if len(a) >= 10 and i + 1 < len(filas):
            b = [limpiar(td.get_text()) for td in filas[i + 1].find_all("td")]
            if len(b) >= 4:
                parejas.append({
                    "n": a_entero(a[0]),
                    "local": [x for x in (a[3], b[1]) if x],
                    "visitante": [x for x in (a[7], b[2]) if x],
                    "sets_local": a_entero(a[4]),
                    "sets_visitante": a_entero(a[6]),
                    "parciales": [[int(x), int(y)] for x, y in re.findall(r"(\d+)/(\d+)", a[5])],
                })
                i += 2
                continue
        i += 1

    return {
        "jornada": a_entero(jornada), "fecha_iso": fecha_iso, "hora": hora,
        "lugar": lugar, "tandas": tandas, "local": local, "visitante": visitante,
        "juegos_local": a_entero(juegos_l), "sets_local": a_entero(sets_l),
        "partidos_local": a_entero(part_l), "partidos_visitante": a_entero(part_v),
        "sets_visitante": a_entero(sets_v), "juegos_visitante": a_entero(juegos_v),
        "parejas": parejas,
    }


def cargar_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_json(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))


def completar_detalles(liga_id, partidos, detalle, ruta_cache):
    """Descarga el detalle de los enfrentamientos jugados que aún no están en la caché."""
    pendientes = []
    for p in partidos:
        if not p["resultado"]:
            continue
        clave = f"{p['grupo_id']}:{p['partido']}"
        previo = detalle.get(clave)
        if previo is None or previo.get("provisional"):  # los sin validar pueden cambiar
            pendientes.append((clave, p))
    print(f"Detalle de enfrentamientos: {len(pendientes)} por descargar, "
          f"{len(detalle)} ya en caché")
    for n, (clave, p) in enumerate(pendientes, 1):
        try:
            html = descargar({"id": liga_id, "partido": p["partido"], "grupo": p["grupo_id"]},
                             url=BASE + "Liga_Resultado")
            d = parsear_resultado(html)
        except requests.RequestException as e:
            print(f"  aviso: no se pudo leer {clave}: {e}")
            continue
        if not d:
            print(f"  aviso: página sin el formato esperado en {clave}")
            continue
        d["grupo_id"] = p["grupo_id"]
        d["partido"] = p["partido"]
        d["provisional"] = p["estado"] != "cerrados"
        detalle[clave] = d
        if n % 50 == 0:
            print(f"  {n}/{len(pendientes)}")
            guardar_json(ruta_cache, detalle)
    guardar_json(ruta_cache, detalle)
    return detalle


def construir_jugadores(clasif, detalle):
    """Estadísticas por jugador a partir de las parejas de cada enfrentamiento."""
    equipos = {(c["grupo_id"], c["equipo"]): c for c in clasif}
    acum = {}
    for d in detalle.values():
        gid = d["grupo_id"]
        for par in d["parejas"]:
            sl, sv = par["sets_local"], par["sets_visitante"]
            if sl + sv == 0:  # no jugado
                continue
            jl = sum(a for a, _ in par["parciales"])
            jv = sum(b for _, b in par["parciales"])
            for lado, equipo in (("local", d["local"]), ("visitante", d["visitante"])):
                sf, sc, gf, gc = (sl, sv, jl, jv) if lado == "local" else (sv, sl, jv, jl)
                for nombre in par[lado]:
                    j = acum.setdefault((gid, equipo, nombre), {
                        "name": nombre, "team": equipo, "categoryId": gid,
                        "played": 0, "won": 0, "lost": 0,
                        "setsFor": 0, "setsAgainst": 0, "gamesFor": 0, "gamesAgainst": 0})
                    j["played"] += 1
                    j["won" if sf > sc else "lost"] += 1
                    j["setsFor"] += sf
                    j["setsAgainst"] += sc
                    j["gamesFor"] += gf
                    j["gamesAgainst"] += gc
    jugadores = []
    for (gid, equipo, _), j in acum.items():
        c = equipos.get((gid, equipo))
        j["teamId"] = c["id_equipo"] if c else ""
        j["category"] = c["grupo"] if c else ""
        j["genero"] = c["genero"] if c else ""
        jugadores.append(j)
    jugadores.sort(key=lambda j: (-j["won"], j["lost"], j["name"]))
    return jugadores


# ---------- Plantillas con puntos y estadísticas de parejas (para la calculadora) ----------

def parsear_plantilla(html):
    """Página Liga_DetalleEquipo: jugadores del equipo con su puntuación actual."""
    soup = BeautifulSoup(html, "html.parser")
    jugadores = []
    for tr in soup.select("tr.lineas"):
        td = [limpiar(x.get_text()) for x in tr.find_all("td")]
        if len(td) < 6 or not (td[1] or td[3]):
            continue
        jugadores.append({"a1": td[1], "a2": td[2], "n": td[3], "cat": td[4], "pts": a_entero(td[5])})
    return jugadores


def sin_tildes(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9 ]", " ", s)


def palabras(s):
    return sin_tildes(s).split()


def buscar_jugador(nombre, candidatos):
    """Índice del jugador cuyo nombre encaja con el del acta ('NOMBRE APELLIDO1'), o None.

    candidatos: lista de dicts con 'tok' (set de palabras de apellido1+apellido2+nombre),
    'nom' (palabras del nombre) y 'ap1' (palabras del primer apellido).
    """
    w = palabras(nombre)
    t = set(w)
    if not t:
        return None
    mejor, mejores = 0, []
    for i, c in enumerate(candidatos):
        s = len(t & c["tok"])
        if s > mejor:
            mejor, mejores = s, [i]
        elif s == mejor and s > 0:
            mejores.append(i)
    if not mejores or not (mejor == len(t) or mejor >= 2):
        return None
    if len(mejores) == 1:
        return mejores[0]
    exactos = [i for i in mejores
               if w[0] in candidatos[i]["nom"] and w[-1] in candidatos[i]["ap1"]]
    return exactos[0] if len(exactos) == 1 else None


def completar_plantillas(liga_id, clasif, ruta, max_edad_horas=12):
    """Descarga la ficha de cada equipo (con los puntos) salvo si la copia es reciente.

    Los puntos solo cambian una vez por semana, así que no hace falta pedirlos en cada ejecución.
    """
    previo = cargar_json(ruta).get("teams", {})
    ahora = datetime.datetime.now(datetime.timezone.utc)
    resultado, descargados = {}, 0
    for c in clasif:
        key = f"{c['grupo_id']}:{c['id_equipo']}"
        if key in resultado:
            continue
        viejo = previo.get(key)
        if viejo and viejo.get("players") is not None and viejo.get("fetchedAt"):
            try:
                edad = ahora - datetime.datetime.fromisoformat(viejo["fetchedAt"])
                if edad < datetime.timedelta(hours=max_edad_horas):
                    resultado[key] = {"players": viejo["players"], "fetchedAt": viejo["fetchedAt"]}
                    continue
            except ValueError:
                pass
        try:
            html = descargar({"IdEquipo": c["id_equipo"], "Id": liga_id, "grupo": c["grupo_id"]},
                             url=BASE + "Liga_DetalleEquipo")
            jugadores = parsear_plantilla(html)
        except requests.RequestException as e:
            print(f"  aviso: no se pudo leer la plantilla de {c['equipo']}: {e}")
            jugadores = viejo["players"] if viejo else []
        resultado[key] = {"players": jugadores, "fetchedAt": ahora.isoformat(timespec="seconds")}
        descargados += 1
        if descargados % 50 == 0:
            print(f"  plantillas: {descargados} descargadas")
    print(f"Plantillas: {descargados} descargadas, {len(resultado) - descargados} reutilizadas")
    return resultado


def construir_plantillas(clasif, detalle, crudo):
    """Une plantillas, puntos y el historial de cada pareja (ganados, 'victorias poco probables')."""
    equipos = {(c["grupo_id"], c["equipo"]): c for c in clasif}
    teams, cand = {}, {}
    for c in clasif:
        key = f"{c['grupo_id']}:{c['id_equipo']}"
        if key in teams:
            continue
        jug = crudo.get(key, {}).get("players", [])
        teams[key] = {"name": c["equipo"], "categoryId": c["grupo_id"], "genero": c["genero"],
                      "fetchedAt": crudo.get(key, {}).get("fetchedAt", ""),
                      "players": jug, "pairs": {}, "last": None}
        cand[key] = [{"tok": set(palabras(f"{j['a1']} {j['a2']} {j['n']}")),
                      "nom": set(palabras(j["n"])), "ap1": set(palabras(j["a1"]))} for j in jug]
    # Búsqueda en toda la liga, para jugadores que juegan con un equipo que no es el suyo (filiales)
    todos = [(k, i) for k in cand for i in range(len(cand[k]))]
    todos_c = [cand[k][i] for k, i in todos]
    memo = {}

    def resolver(nombre, key):
        """-> (key_del_equipo, indice) o None"""
        i = buscar_jugador(nombre, cand.get(key, []))
        if i is not None:
            return key, i
        if nombre not in memo:
            g = buscar_jugador(nombre, todos_c)
            memo[nombre] = todos[g] if g is not None else None
        return memo[nombre]

    def puntos(r):
        return teams[r[0]]["players"][r[1]]["pts"] if r else None

    ordenados = sorted(detalle.values(), key=lambda d: (d.get("fecha_iso") or "", d["partido"]))
    for d in ordenados:
        gid = d["grupo_id"]
        lados = {}
        for lado in ("local", "visitante"):
            c = equipos.get((gid, d[lado]))
            if c:
                lados[lado] = f"{gid}:{c['id_equipo']}"
        if len(lados) < 2:
            continue
        jugado = [p for p in d["parejas"] if p["sets_local"] + p["sets_visitante"] > 0]
        if not jugado:
            continue
        alineacion = {"local": [], "visitante": []}
        for par in sorted(jugado, key=lambda p: p["n"]):
            res = {lado: [resolver(n, lados[lado]) for n in par[lado]] for lado in lados}
            suma = {}
            for lado in lados:
                pts = [puntos(r) for r in res[lado]]
                suma[lado] = sum(pts) if len(pts) == 2 and None not in pts else None
            for lado, otro in (("local", "visitante"), ("visitante", "local")):
                propios = res[lado]
                alineacion[lado].append({"n": par["n"], "nom": par[lado],
                                         "j": [r[1] if r and r[0] == lados[lado] else -1 for r in propios]})
                if len(propios) != 2 or any(r is None or r[0] != lados[lado] for r in propios):
                    continue
                i, j = sorted(r[1] for r in propios)
                gano = (par["sets_local"] > par["sets_visitante"]) == (lado == "local")
                e = teams[lados[lado]]["pairs"].setdefault(f"{i}-{j}", [0, 0, 0, 0])
                e[0] += 1
                e[1] += 1 if gano else 0
                if suma[lado] is not None and suma[otro] is not None and suma[otro] > suma[lado]:
                    e[3] += 1
                    e[2] += 1 if gano else 0
        for lado in lados:  # el último enfrentamiento jugado de cada equipo = su alineación más reciente
            teams[lados[lado]]["last"] = {
                "date": d.get("fecha_iso") or "", "rival": d["visitante" if lado == "local" else "local"],
                "pairs": alineacion[lado]}
    return teams


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="28942", help="id de la liga (parámetro id de la URL)")
    ap.add_argument("--salida", default="datos_liga")
    ap.add_argument("--file", help="parsear un HTML guardado en vez de descargar")
    ap.add_argument("--file-resultado", help="probar el parser con una página Liga_Resultado guardada")
    ap.add_argument("--sin-detalle", action="store_true",
                    help="no descargar el detalle de cada enfrentamiento (más rápido)")
    ap.add_argument("--sin-plantillas", action="store_true",
                    help="no descargar las plantillas con puntos (calculadora de alineaciones)")
    ap.add_argument("--file-plantilla", help="probar el parser con una página Liga_DetalleEquipo guardada")
    args = ap.parse_args()

    if args.file_plantilla:
        with open(args.file_plantilla, "rb") as f:
            crudo = f.read()
        try:
            html = crudo.decode("utf-8")
        except UnicodeDecodeError:
            html = crudo.decode("iso-8859-1")
        print(json.dumps(parsear_plantilla(html), ensure_ascii=False, indent=1))
        return

    if args.file_resultado:
        with open(args.file_resultado, "rb") as f:
            crudo = f.read()
        try:
            html = crudo.decode("utf-8")
        except UnicodeDecodeError:
            html = crudo.decode("iso-8859-1")
        print(json.dumps(parsear_resultado(html), ensure_ascii=False, indent=1))
        return

    os.makedirs(args.salida, exist_ok=True)
    todos_partidos, toda_clasif = [], []

    if args.file:
        with open(args.file, "rb") as f:
            crudo = f.read()
        try:  # un HTML guardado desde el navegador suele estar en UTF-8
            html = crudo.decode("utf-8")
        except UnicodeDecodeError:
            html = crudo.decode("iso-8859-1")
        ctx = {"genero": "", "fase": "", "grupo_id": "", "grupo": ""}
        todos_partidos, toda_clasif = parsear(html, ctx)
    else:
        for genero in ("F", "M"):
            base = {"id": args.id, "genero": genero, "grupo": "-", "jornada": "--"}
            soup = BeautifulSoup(descargar({**base, "fase": 0}), "html.parser")
            fases = opciones(soup, "fase", {"0"}) or [("1", "Fase I")]
            for fase_id, fase_nombre in fases:
                soup = BeautifulSoup(descargar({**base, "fase": fase_id}), "html.parser")
                for grupo_id, grupo_nombre in opciones(soup, "grupo", {"-"}):
                    print(f"{genero} | {fase_nombre} | {grupo_nombre}")
                    html = descargar({**base, "fase": fase_id, "grupo": grupo_id})
                    ctx = {"genero": genero, "fase": fase_nombre,
                           "grupo_id": grupo_id, "grupo": grupo_nombre}
                    p, c = parsear(html, ctx)
                    todos_partidos += p
                    toda_clasif += c

    equipos = [{k: c[k] for k in ("genero", "fase", "grupo_id", "grupo", "id_equipo", "equipo")}
               for c in toda_clasif]
    print("Guardando:")
    guardar(os.path.join(args.salida, "partidos.csv"), todos_partidos)
    guardar(os.path.join(args.salida, "clasificacion.csv"), toda_clasif)
    guardar(os.path.join(args.salida, "equipos.csv"), equipos)

    ruta_cache = os.path.join(args.salida, "detalle.json")
    detalle = cargar_json(ruta_cache)
    if not args.file and not args.sin_detalle:
        detalle = completar_detalles(args.id, todos_partidos, detalle, ruta_cache)

    datos = construir_json(todos_partidos, toda_clasif, args.id, detalle)
    ruta_json = os.path.join(args.salida, "data.json")
    guardar_json(ruta_json, datos)
    print(f"  {ruta_json}: {len(datos['teams'])} equipos, {len(datos['categories'])} categorías")

    jugadores = construir_jugadores(toda_clasif, detalle)
    ruta_jug = os.path.join(args.salida, "jugadores.json")
    guardar_json(ruta_jug, {"updatedAt": datos["updatedAt"], "players": jugadores})
    print(f"  {ruta_jug}: {len(jugadores)} jugadores")

    if not args.file and not args.sin_plantillas:
        ruta_pl = os.path.join(args.salida, "plantillas.json")
        crudo = completar_plantillas(args.id, toda_clasif, ruta_pl)
        plantillas = construir_plantillas(toda_clasif, detalle, crudo)
        guardar_json(ruta_pl, {"updatedAt": datos["updatedAt"], "teams": plantillas})
        con_puntos = sum(1 for t in plantillas.values() if t["players"])
        print(f"  {ruta_pl}: {len(plantillas)} equipos ({con_puntos} con plantilla)")


if __name__ == "__main__":
    main()
